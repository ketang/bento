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

--no-merge is a canary for landing-path changes: it stops after the lease
check (cleanup still runs, and a cleanup failure fails the run) and reports
"merged": false. It still fetches, but does not merge, push, or move any local
branch, and never touches the primary checkout. It never writes or reuses a
verifier evidence record -- the tree is throwaway and a canary must exercise
the real verifier. Errors raised before the driver starts (not a work tree)
carry no mode/merged fields.

--teardown-only is a separate, explicit invocation for land-work step 10, run
after the post hooks and untracked accounting: it fetches, then removes the
feature worktree and deletes its branch from the primary checkout, and sweeps
LSP residue (e.g. rust-analyzer target/flycheck*) recreated at the removed
path. It fails closed and exits 0 with `status: skipped` and a `reason` when
it refuses: primary checkout, feature tip not contained in origin/<primary>,
dirty/untracked files, ignored files outside target/ and the residue globs, or
a `git worktree remove` refusal (e.g. locked). Once removed, the caller's shell
sits in a deleted directory and must `cd` to the reported `cd` path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from git_state import (  # noqa: E402
    NotAWorkTreeError,
    current_branch,
    detect_checkout_root,
    detect_primary_branch,
    git,
    git_stdout,
    is_linked_worktree,
    primary_checkout_root,
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
    parser.add_argument(
        "--no-merge", action="store_true",
        help="canary: run prepare, fetch, create-preview, verify and lease check, clean up the "
        "preview, then stop without merging, pushing, or touching the primary checkout",
    )
    parser.add_argument(
        "--teardown-only", action="store_true",
        help="after a landing: remove the feature worktree and branch (fails closed; see module doc)",
    )
    parser.add_argument("--worktree", help="with --teardown-only: the feature worktree (default: cwd)")
    parser.add_argument("--branch", help="with --teardown-only: assert the worktree is on this branch")
    args = parser.parse_args()
    if args.teardown_only and args.no_merge:
        parser.error("--teardown-only cannot be combined with --no-merge")
    if (args.worktree or args.branch) and not args.teardown_only:
        parser.error("--worktree and --branch require --teardown-only")
    return args


# -- teardown --------------------------------------------------------------- #

# Files a still-running LSP recreates under a removed worktree. Extendable via
# <scope>/agent-plugins/bento/bento/land-work/residue-globs.txt (the doctor
# carries an identical copy of this matcher).
DEFAULT_RESIDUE_GLOBS = ("target/flycheck*/**",)
RESIDUE_WAIT_SECONDS = 2.0
_RESIDUE_FILE = "agent-plugins/bento/bento/land-work/residue-globs.txt"


def valid_residue_glob(glob: str) -> bool:
    """Relative, no `..`, and a literal first segment, so a tracked globs file
    cannot widen the sweep to arbitrary paths."""
    parts = glob.split("/")
    return bool(glob) and "\\" not in glob and ".." not in parts and bool(parts[0]) and "*" not in parts[0]


def residue_globs(primary_root: Path) -> list[str]:
    globs = list(DEFAULT_RESIDUE_GLOBS)
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    # Repo scope overrides home scope, per file.
    for candidate in (primary_root / ".agent-plugins/bento/bento/land-work/residue-globs.txt", Path(xdg) / _RESIDUE_FILE):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = (ln.strip() for ln in text.splitlines())
        globs += [ln for ln in lines if ln and not ln.startswith("#") and valid_residue_glob(ln)]
        break
    return globs


def residue_regexes(globs: list[str]) -> list[re.Pattern[str]]:
    patterns = []
    for glob in globs:
        body = "".join(
            ".*" if part == "**" else "[^/]*".join(re.escape(p) for p in part.split("*"))
            for part in re.split(r"(\*\*)", glob)
        )
        patterns.append(re.compile(body + r"\Z"))
    return patterns


def non_residue_files(path: Path, patterns: list[re.Pattern[str]]) -> list[str]:
    """Relative paths under `path` matching no residue glob. Symlinked
    directories count as files; an unreadable tree is never residue."""
    def _raise(exc: OSError) -> None:
        raise exc

    left = []
    try:
        for dirpath, dirs, files in os.walk(path, onerror=_raise):
            names = files + [d for d in dirs if (Path(dirpath) / d).is_symlink()]
            for name in names:
                rel = (Path(dirpath) / name).relative_to(path).as_posix()
                if not any(p.match(rel) for p in patterns):
                    left.append(rel)
    except OSError:
        return ["<unreadable>"]
    return sorted(left)


def _residue_wait() -> float:
    try:
        return max(0.0, float(os.environ.get("BENTO_LAND_TEST_RESIDUE_WAIT", RESIDUE_WAIT_SECONDS)))
    except ValueError:
        return RESIDUE_WAIT_SECONDS


def _teardown_checked(worktree: Path, primary_root: Path, branch: str, primary_branch: str, report: dict) -> dict:
    def skip(reason: str) -> dict:
        report["reason"] = reason
        return report

    if worktree == primary_root:
        return skip("refusing to remove the primary checkout")
    if not branch:
        return skip("worktree has a detached HEAD")
    if branch == primary_branch:
        return skip(f"worktree is on the primary branch {primary_branch}")
    git("fetch", "origin", primary_branch, cwd=primary_root, check=False)
    remote_ref = f"refs/remotes/origin/{primary_branch}"
    if not ref_exists(remote_ref, primary_root):
        return skip(f"no {remote_ref} to verify the landing against")
    tip = rev_parse("HEAD", worktree)
    if git("merge-base", "--is-ancestor", tip, remote_ref, cwd=primary_root, check=False).returncode != 0:
        return skip(f"feature tip {tip[:12]} is not contained in origin/{primary_branch}; not landed")

    status = git("status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching", cwd=worktree, check=False)
    if status.returncode != 0:
        return skip(f"could not inspect the worktree: {status.stderr.strip()}")
    dirty, ignored = [], []
    for line in status.stdout.splitlines():
        (ignored if line.startswith("!! ") else dirty).append(line[3:])
    if dirty:
        return skip(f"dirty: {', '.join(dirty[:10])}" + (" ..." if len(dirty) > 10 else ""))
    globs = residue_globs(primary_root)
    allowed = {"target", *(g.split("/")[0] for g in globs)}
    precious = [p for p in ignored if p.rstrip("/").split("/")[0] not in allowed]
    if precious:
        return skip(f"ignored files would be deleted: {', '.join(precious[:10])}" + (" ..." if len(precious) > 10 else ""))

    # From the primary checkout: this process's own cwd is the worktree.
    removed = git("worktree", "remove", str(worktree), cwd=primary_root, check=False)
    if removed.returncode != 0:
        return skip(f"git worktree remove refused: {removed.stderr.strip()}")
    os.chdir(primary_root)
    report["status"] = "removed"
    # merge-base above is the real guard; -d is the second.
    deleted = git("branch", "-d", branch, cwd=primary_root, check=False)
    report["branch_deleted"] = deleted.returncode == 0
    if not report["branch_deleted"]:
        report["warning"] = f"git branch -d {branch} failed: {deleted.stderr.strip()}"

    # A still-running LSP (rust-analyzer flycheck) may recreate the path.
    time.sleep(_residue_wait())
    hook = os.environ.get("BENTO_LAND_TEST_AFTER_REMOVE")  # test seam: stands in for the LSP
    if hook:
        subprocess.run([hook, str(worktree)], stdin=subprocess.DEVNULL, capture_output=True, check=False)
    if worktree.exists():
        left = ["<symlink>"] if worktree.is_symlink() else non_residue_files(worktree, residue_regexes(globs))
        report["residue_left"] = left
        if left:
            report["warning"] = f"left {worktree}: it contains non-residue files"
        else:
            shutil.rmtree(worktree, ignore_errors=True)
            report["residue_removed"] = not worktree.exists()
    return report


def teardown(cwd: Path, worktree_arg: str | None, branch_arg: str | None) -> dict:
    worktree = detect_checkout_root(Path(worktree_arg).resolve() if worktree_arg else cwd).resolve()
    primary_root = primary_checkout_root(worktree).resolve()
    primary_branch, _ = detect_primary_branch(worktree)
    branch = current_branch(worktree)
    report: dict = {
        "ok": True, "mode": "teardown-only", "status": "skipped", "worktree": str(worktree),
        "branch": branch, "branch_deleted": False, "residue_removed": False, "residue_left": [],
        "cd": str(primary_root),
    }
    if branch_arg and branch_arg != branch:
        report["reason"] = f"worktree is on {branch}, not {branch_arg}"
        return report
    try:
        return _teardown_checked(worktree, primary_root, branch, primary_branch, report)
    except Exception as exc:  # noqa: BLE001 -- the landing is already done; never fail on cleanup
        report["status"] = "error" if report["status"] == "skipped" else report["status"]
        report["warning"] = f"teardown error: {exc}"
        return report


class Driver:
    def __init__(self, cwd: Path, runtime: str, timeout: str | None, no_merge: bool = False):
        self.cwd = cwd
        self.no_merge = no_merge
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
        if entry.get("reused"):
            line += f" [reused, not executed] (tree {str(entry.get('reused_tree'))[:12]})"
        elif "cached" in entry:
            line += " [cached]" if entry["cached"] else " [executed]"
        print(line, file=sys.stderr)
        if entry.get("warning"):
            print(f"  warning: {entry['warning']}", file=sys.stderr)

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
            if payload.get("reused"):
                extra["reused"] = True
                extra["reused_from"] = payload.get("reused_from")
                extra["reused_tree"] = payload.get("reused_tree")
            elif executed_flags:
                extra["cached"] = not any(executed_flags)

        self._record(step, "passed" if ok else "failed", start, extra or None)
        if not ok:
            message = "; ".join(payload.get("errors") or []) or result.stderr.strip() or f"{script.name} exited {result.returncode}"
            conflicts = payload.get("conflicting_paths") if step == "create_preview" else None
            if conflicts:
                hint = (
                    f"rebase required: conflicts in {', '.join(conflicts)}; rebase onto "
                    f"origin/{payload.get('primary_branch')}, resolve, and re-run land.py"
                )
                errors = payload.get("errors") or []
                message = hint if errors == ["merge preview has conflicts"] else f"{message}; {hint}"
            raise StepFailure(step, message, output_path=payload.get("verifier_log"))
        return payload

    def cleanup_preview(self) -> bool:
        if self.preview_dir is None:
            return True
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
        return ok

    def abort_primary_merge_if_in_progress(self) -> None:
        # A canary never merges, so any merge in the primary is the operator's.
        if self.primary_root is None or self.no_merge:
            return
        if (self.primary_root / ".git" / "MERGE_HEAD").exists():
            subprocess.run(["git", "merge", "--abort"], cwd=self.primary_root, capture_output=True, check=False)

    # -- the merge+push step ------------------------------------------------ #
    #
    # Each route returns (merge_sha, merge_tree, verify_ref, warning):
    #   verify_ref   the ref verify_landing should check (None = its default,
    #                the local primary branch ref)
    #   warning      a non-fatal problem to surface even though the landing
    #                itself succeeded (None = no warning)

    def _merge_and_push(
        self, primary_root: Path, primary_branch: str, feature_branch: str,
        primary_local_vs_remote: str | None, preview_tree: str, leased_sha: str,
    ) -> tuple[str, str, str | None, str | None]:
        if primary_local_vs_remote in _PUSH_FROM_PREVIEW_STATUSES:
            return self._push_from_preview(primary_root, primary_branch, feature_branch)
        return self._merge_in_primary(primary_root, primary_branch, feature_branch, preview_tree, leased_sha)

    def _merge_in_primary(
        self, primary_root: Path, primary_branch: str, feature_branch: str,
        preview_tree: str, leased_sha: str,
    ) -> tuple[str, str, str | None, str | None]:
        # The preview was built by merging feature onto leased_sha (bento-
        # rdtn.5's compare-and-set base), not onto whatever the primary
        # checkout's local branch currently points at. "behind" means those
        # differ -- fast-forward the primary to leased_sha first, or the
        # merge here reproduces a different (stale) tree than the verified
        # preview. "equal"/None already coincide with leased_sha by
        # construction, so this is a no-op for them.
        if rev_parse("HEAD", primary_root) != leased_sha:
            git("fetch", "origin", cwd=primary_root, check=False)
            sync = git("merge", "--ff-only", leased_sha, cwd=primary_root, check=False)
            if sync.returncode != 0:
                raise StepFailure(
                    "merge_push",
                    "could not fast-forward the primary checkout to the leased base "
                    f"{leased_sha} before merging: {sync.stderr.strip()}",
                )

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
        return rev_parse("HEAD", primary_root), merged_tree, None, None

    def _push_from_preview(
        self, primary_root: Path, primary_branch: str, feature_branch: str,
    ) -> tuple[str, str, str | None, str | None]:
        assert self.preview_dir is not None
        commit = git(
            "commit", "-m", f"Merge branch '{feature_branch}'", cwd=self.preview_dir, check=False,
        )
        if commit.returncode != 0:
            raise StepFailure("merge_push", commit.stderr.strip() or "git commit failed in the preview worktree")
        # Resolved from the preview itself, before push: this is the
        # authoritative landed commit regardless of whether the primary
        # checkout's local sync below succeeds.
        merge_sha = rev_parse("HEAD", self.preview_dir)
        merge_tree = tree_for_ref("HEAD", self.preview_dir)

        push = git(
            "push", "origin", f"HEAD:refs/heads/{primary_branch}", cwd=self.preview_dir, check=False,
        )
        if push.returncode != 0:
            raise StepFailure("merge_push", push.stderr.strip() or "git push (from preview) failed")

        # The landing itself is now complete (origin has the new commit).
        # Syncing the primary checkout's local branch to match is a
        # best-effort convenience, not part of the landing: the primary may
        # have gained a local-only commit unrelated to this feature branch
        # (e.g. a race between this driver's own prepare step and this point),
        # in which case --ff-only legitimately can't fast-forward even
        # though the push already succeeded. Never force-reset here -- that
        # could discard real local work -- just warn and leave it for the
        # operator to reconcile by hand.

        # Test-only seam: lets the test suite deterministically inject a
        # primary-checkout commit in the window between push and this sync,
        # instead of racing real git/filesystem timing. Never set in
        # production use.
        delay = os.environ.get("BENTO_LAND_TEST_DELAY_PRIMARY_SYNC")
        if delay:
            time.sleep(float(delay))

        fetch = git("fetch", "origin", cwd=primary_root, check=False)
        ff = (
            git("merge", "--ff-only", f"origin/{primary_branch}", cwd=primary_root, check=False)
            if fetch.returncode == 0 else fetch
        )
        if ff.returncode != 0:
            warning = (
                f"pushed {merge_sha} to origin/{primary_branch}, but could not "
                f"fast-forward the primary checkout's local branch to match "
                f"({ff.stderr.strip()}); it likely has an unrelated local-only "
                f"commit -- reconcile it by hand (fetch + rebase or merge), do not "
                "force-reset it"
            )
            return merge_sha, merge_tree, f"refs/remotes/origin/{primary_branch}", warning
        return merge_sha, merge_tree, None, None

    def finish(self, payload: dict) -> dict:
        if self.no_merge:
            payload.update(mode="no-merge", merged=False)
        return payload

    # -- the full sequence --------------------------------------------------- #

    def run(self) -> dict:
        prepare = self._run_script("prepare", PREPARE, [])
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

        preview = self._run_script(
            "create_preview", CREATE_PREVIEW, ["--base-ref", leased_sha, "--owner-pid", str(os.getpid())]
        )
        self.preview_dir = Path(preview["preview_dir"])
        head_sha = preview["feature_sha"]
        preview_tree = preview["preview_tree"]

        # Diff from the merge-base so the verifier sees only the feature's own
        # changes, not the reverse of commits the primary gained since.
        mb = git("merge-base", leased_sha, head_sha, cwd=self.cwd, check=False)
        if mb.returncode != 0 or not mb.stdout.strip():
            raise StepFailure("verify", f"could not compute merge-base of {leased_sha} and {head_sha}: {mb.stderr.strip()}")
        verifier_args = [
            "--repo-root", str(self.cwd),
            "--candidate", str(self.preview_dir),
            "--base-sha", mb.stdout.strip(),
            "--head-sha", head_sha,
            "--runtime", self.runtime,
        ]
        # A canary must really execute the verifier (a real landing's record
        # would let it skip) and must not leave a record for its throwaway tree.
        verifier_args += ["--no-record-evidence"] if self.no_merge else ["--reuse-evidence"]
        if self.timeout:
            verifier_args += ["--timeout", self.timeout]
        self._run_script("verify", RUN_VERIFIER, verifier_args)

        self._run_script("lease_check", VERIFY_LEASE, ["--expected-sha", leased_sha])

        if self.no_merge:
            if not self.cleanup_preview():
                raise StepFailure("cleanup", "could not remove the canary preview worktree")
            return self.finish({
                "ok": True,
                "steps": self.steps,
                "failed_step": None,
                "error": None,
                "preview_tree": preview_tree,
                "primary_branch": primary_branch,
            })

        start = time.monotonic()
        merge_sha, merge_tree, verify_ref, merge_warning = self._merge_and_push(
            primary_root, primary_branch, feature_branch, primary_local_vs_remote, preview_tree, leased_sha,
        )
        self._record("merge_push", "passed", start, {"warning": merge_warning} if merge_warning else None)

        # bento-rdtn.3: cleanup before verify-landing, so a skipped cleanup
        # fails verify-landing instead of leaking a preview worktree -- but
        # only for a scratch preview. A persistent landing.integration_worktree
        # is never removed (create-preview.py's --cleanup is a documented
        # no-op against it), so passing --preview-dir here would always fail
        # verify-landing for repos configured that way.
        persistent_worktree = bool(preview.get("persistent_worktree"))
        preview_dir_for_verify = None if persistent_worktree else str(self.preview_dir)
        self.cleanup_preview()

        verify_args = ["--expected-tree", merge_tree]
        if preview_dir_for_verify:
            verify_args += ["--preview-dir", preview_dir_for_verify]
        if verify_ref:
            verify_args += ["--ref", verify_ref]
        self._run_script("verify_landing", VERIFY_LANDING, verify_args)

        return {
            "ok": True,
            "steps": self.steps,
            "failed_step": None,
            "error": None,
            "merge_sha": merge_sha,
            "primary_branch": primary_branch,
            "warning": merge_warning,
        }


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    if args.teardown_only:
        result = teardown(cwd, args.worktree, args.branch)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        for key in ("reason", "warning"):
            if result.get(key):
                print(f"teardown {key}: {result[key]}", file=sys.stderr)
        return 0
    driver = Driver(cwd, args.runtime, args.timeout, args.no_merge)

    def _on_signal(signum, _frame):
        driver.cleanup_preview()
        driver.abort_primary_merge_if_in_progress()
        payload = driver.finish({
            "ok": False,
            "steps": driver.steps,
            "failed_step": "interrupted",
            "error": f"interrupted by signal {signum}",
        })
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
        result = driver.finish({
            "ok": False,
            "steps": driver.steps,
            "failed_step": exc.step,
            "error": exc.message,
            "output_path": exc.output_path,
        })
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
