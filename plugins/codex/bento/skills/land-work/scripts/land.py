#!/usr/bin/env python3
"""Single orchestrating driver for the land-work landing sequence (bento-rdtn.14).

Runs prepare -> fetch -> create-preview -> run-verifier -> verify-lease
(recheck) -> merge+push -> verify-landing -> cleanup, stopping at the first
failed step and always removing the preview worktree via a finally block --
including on SIGINT/SIGTERM. Wraps the existing land-work-*.py scripts as
subprocesses rather than reimplementing their logic (bento-rdtn.3-.6 and
bento-rdtn.13 already own those individual fixes); this script is only the
sequencing, timing, cleanup, and the merge+push step no existing script
performs.

The merge+push step takes one of two routes, chosen from land-work-
prepare.py's own primary_local_vs_remote diagnostic (bento-rdtn.5):
  - normal route (equal/behind/null): merge --no-ff in the primary checkout,
    then push it.
  - push-from-preview route (ahead/diverged): finish the preview's --no-commit
    merge into a real commit there, push straight from the preview to the
    leased remote, then fast-forward-only sync the primary.

Run from the feature-branch worktree, exactly like every other land-work
script. Prints one line per step to stderr as each completes
(step, status, seconds[, executed/cached for the verify step]); the final
JSON diagnostics object goes to stdout. Exit 0 means landed; any nonzero exit
stops before the next step and always leaves the preview cleaned up.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from git_state import (  # noqa: E402
    NotAWorkTreeError,
    git,
    git_stdout,
    ref_exists,
    rev_parse,
    tree_for_ref,
)

PREPARE = SCRIPT_DIR / "land-work-prepare.py"
CREATE_PREVIEW = SCRIPT_DIR / "land-work-create-preview.py"
RUN_VERIFIER = SCRIPT_DIR / "land-work-run-verifier.py"
VERIFY_LEASE = SCRIPT_DIR / "land-work-verify-lease.py"
VERIFY_LANDING = SCRIPT_DIR / "land-work-verify-landing.py"

# Routes for the merge+push step, from land-work-prepare.py's
# primary_local_vs_remote diagnostic. `None` (no remote-tracking ref to
# compare against) takes the normal route -- nothing indicates divergence.
_PUSH_FROM_PREVIEW_STATUSES = frozenset({"ahead", "diverged"})


class StepFailure(Exception):
    def __init__(self, step: str, message: str, output_path: str | None = None):
        super().__init__(message)
        self.step = step
        self.message = message
        self.output_path = output_path


class Interrupted(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", help="verifier command timeout in seconds, forwarded to land-work-run-verifier.py")
    parser.add_argument("--runtime", default="unknown", help="agent runtime: claude, codex, or unknown")
    return parser.parse_args()


class Driver:
    def __init__(self, cwd: Path, runtime: str, timeout: str | None):
        self.cwd = cwd
        self.runtime = runtime
        self.timeout = timeout
        self.steps: list[dict] = []
        self.preview_dir: Path | None = None
        self.primary_root: Path | None = None

    # -- bookkeeping ------------------------------------------------------- #

    def _record(self, name: str, status: str, start: float, extra: dict | None = None) -> None:
        entry: dict = {"step": name, "status": status, "seconds": round(time.monotonic() - start, 3)}
        if extra:
            entry.update(extra)
        self.steps.append(entry)
        line = f"{name}: {status} ({entry['seconds']}s)"
        if "cached" in entry:
            line += " [cached]" if entry["cached"] else " [executed]"
        print(line, file=sys.stderr)

    def _run_script(self, step: str, script: Path, args: list[str]) -> dict:
        start = time.monotonic()
        result = subprocess.run(
            [str(script), *args], capture_output=True, text=True, cwd=self.cwd, check=False,
        )
        try:
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except ValueError:
            payload = {}
        ok = result.returncode == 0 and bool(payload.get("ok", result.returncode == 0))

        extra: dict = {}
        if step == "verify":
            checks = payload.get("selected_checks") or []
            executed_flags = [c.get("executed") for c in checks if c.get("executed") is not None]
            if executed_flags:
                extra["cached"] = not any(executed_flags)

        self._record(step, "passed" if ok else "failed", start, extra or None)
        if not ok:
            message = "; ".join(payload.get("errors") or []) or result.stderr.strip() or f"{script.name} exited {result.returncode}"
            raise StepFailure(step, message, output_path=payload.get("verifier_log"))
        return payload

    def cleanup_preview(self) -> None:
        if self.preview_dir is None:
            return
        start = time.monotonic()
        try:
            result = subprocess.run(
                [str(CREATE_PREVIEW), "--cleanup", "--preview-dir", str(self.preview_dir)],
                capture_output=True, text=True, cwd=self.cwd, check=False,
            )
            ok = result.returncode == 0
        except OSError:
            ok = False
        self._record("cleanup", "passed" if ok else "failed", start)
        self.preview_dir = None

    def abort_primary_merge_if_in_progress(self) -> None:
        if self.primary_root is None:
            return
        if (self.primary_root / ".git" / "MERGE_HEAD").exists():
            subprocess.run(["git", "merge", "--abort"], cwd=self.primary_root, capture_output=True, check=False)

    # -- the merge+push step ------------------------------------------------ #

    def _merge_and_push(
        self, primary_root: Path, primary_branch: str, feature_branch: str,
        primary_local_vs_remote: str | None, preview_tree: str,
    ) -> tuple[str, str]:
        if primary_local_vs_remote in _PUSH_FROM_PREVIEW_STATUSES:
            return self._push_from_preview(primary_root, primary_branch, feature_branch)
        return self._merge_in_primary(primary_root, primary_branch, feature_branch, preview_tree)

    def _merge_in_primary(
        self, primary_root: Path, primary_branch: str, feature_branch: str, preview_tree: str,
    ) -> tuple[str, str]:
        # Test-only seam: lets the test suite deterministically position a
        # SIGINT mid-merge instead of racing real git timing. Never set in
        # production use.
        delay = os.environ.get("BENTO_LAND_TEST_DELAY_MERGE")
        if delay:
            time.sleep(float(delay))
        result = git(
            "merge", "--no-ff", feature_branch, "-m", f"Merge branch '{feature_branch}'",
            cwd=primary_root, check=False,
        )
        if result.returncode != 0:
            self.abort_primary_merge_if_in_progress()
            raise StepFailure("merge_push", result.stderr.strip() or "git merge failed in the primary checkout")
        merged_tree = tree_for_ref("HEAD", primary_root)
        if merged_tree != preview_tree:
            # The merge in the primary produced a different tree than the
            # verified preview -- do not push an unverified candidate.
            subprocess.run(["git", "reset", "--hard", "HEAD@{1}"], cwd=primary_root, capture_output=True, check=False)
            raise StepFailure(
                "merge_push",
                f"merge in the primary checkout produced tree {merged_tree} but the "
                f"verified preview tree was {preview_tree}; reset the primary and stopped "
                "before pushing an unverified candidate",
            )
        push = git("push", "origin", primary_branch, cwd=primary_root, check=False)
        if push.returncode != 0:
            raise StepFailure("merge_push", push.stderr.strip() or "git push failed")
        return rev_parse("HEAD", primary_root), merged_tree

    def _push_from_preview(
        self, primary_root: Path, primary_branch: str, feature_branch: str,
    ) -> tuple[str, str]:
        assert self.preview_dir is not None
        commit = git(
            "commit", "-m", f"Merge branch '{feature_branch}'", cwd=self.preview_dir, check=False,
        )
        if commit.returncode != 0:
            raise StepFailure("merge_push", commit.stderr.strip() or "git commit failed in the preview worktree")
        push = git(
            "push", "origin", f"HEAD:refs/heads/{primary_branch}", cwd=self.preview_dir, check=False,
        )
        if push.returncode != 0:
            raise StepFailure("merge_push", push.stderr.strip() or "git push (from preview) failed")
        fetch = git("fetch", "origin", cwd=primary_root, check=False)
        if fetch.returncode != 0:
            raise StepFailure("merge_push", fetch.stderr.strip() or "git fetch failed in the primary checkout")
        ff = git("merge", "--ff-only", f"origin/{primary_branch}", cwd=primary_root, check=False)
        if ff.returncode != 0:
            raise StepFailure("merge_push", ff.stderr.strip() or "git merge --ff-only failed in the primary checkout")
        return rev_parse("HEAD", primary_root), tree_for_ref("HEAD", primary_root)

    # -- the full sequence --------------------------------------------------- #

    def run(self) -> dict:
        prepare = self._run_script("prepare", PREPARE, ["--require-up-to-date"])
        primary_branch = prepare["primary_branch"]
        feature_branch = prepare["branch"]
        primary_root = Path(prepare["primary_checkout_root"])
        self.primary_root = primary_root
        primary_local_vs_remote = prepare.get("primary_local_vs_remote")

        start = time.monotonic()
        git("fetch", "origin", primary_branch, cwd=self.cwd, check=False)
        remote_ref = f"refs/remotes/origin/{primary_branch}"
        leased_sha = (
            git_stdout("rev-parse", remote_ref, cwd=self.cwd)
            if ref_exists(remote_ref, self.cwd)
            else git_stdout("rev-parse", f"refs/heads/{primary_branch}", cwd=self.cwd)
        )
        self._record("fetch", "passed", start)

        preview = self._run_script("create_preview", CREATE_PREVIEW, ["--base-ref", leased_sha])
        self.preview_dir = Path(preview["preview_dir"])
        head_sha = preview["feature_sha"]
        preview_tree = preview["preview_tree"]

        verifier_args = [
            "--repo-root", str(self.cwd),
            "--candidate", str(self.preview_dir),
            "--base-sha", leased_sha,
            "--head-sha", head_sha,
            "--runtime", self.runtime,
        ]
        if self.timeout:
            verifier_args += ["--timeout", self.timeout]
        self._run_script("verify", RUN_VERIFIER, verifier_args)

        self._run_script("lease_check", VERIFY_LEASE, ["--expected-sha", leased_sha])

        start = time.monotonic()
        merge_sha, merge_tree = self._merge_and_push(
            primary_root, primary_branch, feature_branch, primary_local_vs_remote, preview_tree,
        )
        self._record("merge_push", "passed", start)

        # bento-rdtn.3: cleanup before verify-landing, so a skipped cleanup
        # fails verify-landing instead of leaking a preview worktree.
        preview_dir_for_verify = str(self.preview_dir)
        self.cleanup_preview()

        self._run_script(
            "verify_landing", VERIFY_LANDING,
            ["--expected-tree", merge_tree, "--preview-dir", preview_dir_for_verify],
        )

        return {
            "ok": True,
            "steps": self.steps,
            "failed_step": None,
            "error": None,
            "merge_sha": merge_sha,
            "primary_branch": primary_branch,
        }


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    driver = Driver(cwd, args.runtime, args.timeout)

    def _on_signal(signum, _frame):
        driver.cleanup_preview()
        driver.abort_primary_merge_if_in_progress()
        payload = {
            "ok": False,
            "steps": driver.steps,
            "failed_step": "interrupted",
            "error": f"interrupted by signal {signum}",
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        sys.exit(128 + signum)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        result = driver.run()
    except StepFailure as exc:
        driver.cleanup_preview()
        driver.abort_primary_merge_if_in_progress()
        result = {
            "ok": False,
            "steps": driver.steps,
            "failed_step": exc.step,
            "error": exc.message,
            "output_path": exc.output_path,
        }
    except BaseException:
        driver.cleanup_preview()
        driver.abort_primary_merge_if_in_progress()
        raise

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except NotAWorkTreeError as exc:
        json.dump(exc.diagnostic, sys.stdout, indent=2)
        sys.stdout.write("\n")
        exit_code = 1
    raise SystemExit(exit_code)
