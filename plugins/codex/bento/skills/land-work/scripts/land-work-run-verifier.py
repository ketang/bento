#!/usr/bin/env python3
"""Deterministic land-work project-verifier gate.

Landing must never equate a zero-check project result with verified candidate
evidence (bento-pnrl). This helper:

1. discovers the land-work verifier manifest (repo-local overrides XDG, first
   existing wins as a whole — no cross-root merge);
2. builds the deduplicated repo-relative Git path union of everything the
   candidate would land (committed base..head, staged, unstaged, and
   nonignored untracked), in the *supplied candidate worktree only*;
3. subtracts only exact, valid `verified_noop` exemptions;
4. runs the manifest command in the candidate worktree and parses its final
   stdout line as the verifier result JSON;
5. fails closed unless a `passed` verifier covers every remaining relevant
   path with at least one passed selected check (or nothing relevant remains).

A missing manifest with a nonempty relevant diff is a landing failure that
reports the config path to create. Generic land-work/pre hooks are unrelated:
their exit 0 never counts as project verification here.

Diagnostics are emitted as one JSON object on stdout and never include file
contents. Exit 0 means verified; any nonzero exit stops landing before lease
verification or merge.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# lifecycle_extensions lives beside the launch-work scripts; both skills sit
# under a shared skills/ root in the catalog and in every generated plugin.
_LAUNCH_SCRIPTS = SCRIPT_DIR.parents[1] / "launch-work" / "scripts"
sys.path.insert(0, str(_LAUNCH_SCRIPTS))

import lifecycle_extensions  # type: ignore  # noqa: E402


GLOB_CHARS = set("*?[]")


def _git(candidate: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(candidate), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_name_status(output: str) -> tuple[list[str], set[str]]:
    """Return (changed_paths, deleted_paths) from a --name-status -z stream.

    Renames/copies (R###, C###) contribute both the old and new path; the old
    path counts as a deletion side. Straight deletions (D) contribute the path
    as both changed and deleted.
    """
    changed: list[str] = []
    deleted: set[str] = set()
    fields = [f for f in output.split("\0") if f != ""]
    i = 0
    while i < len(fields):
        status = fields[i]
        i += 1
        if status[:1] in ("R", "C"):
            if i + 1 >= len(fields):
                break
            old_path, new_path = fields[i], fields[i + 1]
            i += 2
            changed.append(old_path)
            changed.append(new_path)
            deleted.add(old_path)
        else:
            if i >= len(fields):
                break
            path = fields[i]
            i += 1
            changed.append(path)
            if status[:1] == "D":
                deleted.add(path)
    return changed, deleted


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def _validate_exemption(path_value: str) -> tuple[str | None, str | None]:
    """Return (normalized_path, error). Reject anything but an exact rel path."""
    if path_value.startswith("/"):
        return None, f"absolute path not allowed: {path_value!r}"
    if any(char in GLOB_CHARS for char in path_value):
        return None, f"glob patterns not allowed: {path_value!r}"
    if path_value.endswith("/"):
        return None, f"directory/prefix entry not allowed: {path_value!r}"
    parts = [segment for segment in path_value.split("/") if segment != ""]
    if not parts:
        return None, f"empty path not allowed: {path_value!r}"
    if any(segment == ".." for segment in parts):
        return None, f"'..' not allowed: {path_value!r}"
    parts = [segment for segment in parts if segment != "."]
    if not parts:
        return None, f"empty path not allowed: {path_value!r}"
    return "/".join(parts), None


def _fail(diagnostics: dict, errors: list[str]) -> int:
    diagnostics["errors"] = errors
    diagnostics["ok"] = False
    json.dump(diagnostics, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, help="repo root used for manifest discovery")
    parser.add_argument("--candidate", required=True, help="candidate worktree to inspect and run the verifier in")
    parser.add_argument("--base-sha", required=True, help="committed base revision of the candidate")
    parser.add_argument("--head-sha", required=True, help="committed head revision of the candidate")
    parser.add_argument("--base-ref", default="", help="human-facing base ref name (diagnostics only)")
    parser.add_argument("--runtime", default="unknown", help="agent runtime: claude, codex, or unknown")
    parser.add_argument("--timeout", default="", help="verifier command timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    candidate = Path(args.candidate).resolve()

    diagnostics: dict = {
        "repo_root": str(repo_root),
        "candidate": str(candidate),
        "base_ref": args.base_ref,
        "base_sha": args.base_sha,
        "head_sha": args.head_sha,
        "runtime": args.runtime,
        "manifest_path": None,
        "changed_paths": {"committed": [], "staged": [], "unstaged": [], "untracked": []},
        "relevant_paths": [],
        "exemptions": [],
        "verifier_command": None,
        "verifier_status": None,
        "selected_check_count": 0,
        "unverified_paths": [],
    }

    if not candidate.is_dir():
        return _fail(diagnostics, [f"candidate worktree does not exist: {candidate}"])

    # ---- Build the Git path union in the candidate worktree only. ---------- #
    committed = _git(candidate, "diff", "--name-status", "--find-renames", "-z", args.base_sha, args.head_sha)
    if committed.returncode != 0:
        return _fail(diagnostics, [f"git diff {args.base_sha}..{args.head_sha} failed: {committed.stderr.strip()}"])
    committed_changed, committed_deleted = _parse_name_status(committed.stdout)

    staged = _git(candidate, "diff", "--cached", "--name-status", "--find-renames", "-z")
    if staged.returncode != 0:
        return _fail(diagnostics, [f"git diff --cached failed: {staged.stderr.strip()}"])
    staged_changed, staged_deleted = _parse_name_status(staged.stdout)

    unstaged = _git(candidate, "diff", "--name-status", "--find-renames", "-z")
    if unstaged.returncode != 0:
        return _fail(diagnostics, [f"git diff failed: {unstaged.stderr.strip()}"])
    unstaged_changed, unstaged_deleted = _parse_name_status(unstaged.stdout)

    untracked_proc = _git(candidate, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked_proc.returncode != 0:
        return _fail(diagnostics, [f"git ls-files --others failed: {untracked_proc.stderr.strip()}"])
    untracked_changed = [f for f in untracked_proc.stdout.split("\0") if f != ""]

    diagnostics["changed_paths"] = {
        "committed": _dedupe(committed_changed),
        "staged": _dedupe(staged_changed),
        "unstaged": _dedupe(unstaged_changed),
        "untracked": _dedupe(untracked_changed),
    }
    deleted_paths = committed_deleted | staged_deleted | unstaged_deleted
    union = _dedupe(
        committed_changed + staged_changed + unstaged_changed + untracked_changed
    )

    # ---- Discover and validate the verifier manifest. ---------------------- #
    discovery = lifecycle_extensions.discover_verifier(repo_root)
    if discovery.manifest_path is not None:
        diagnostics["manifest_path"] = str(discovery.manifest_path)

    if discovery.manifest is None:
        if not union:
            # Nothing relevant would land; there is nothing to verify.
            diagnostics["relevant_paths"] = []
            diagnostics["ok"] = True
            diagnostics["errors"] = []
            json.dump(diagnostics, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        if discovery.errors:
            return _fail(diagnostics, discovery.errors)
        required = discovery.searched_paths[0] if discovery.searched_paths else None
        return _fail(
            diagnostics,
            [
                "no verifier manifest configured but the candidate has a nonempty "
                "relevant diff; create a verifier manifest at "
                f"{required} — the bento:wire-land-verifier skill scaffolds it",
            ],
        )

    manifest = discovery.manifest
    diagnostics["verifier_command"] = list(manifest.command)

    if not union:
        # Nothing relevant would land; there is nothing to verify, so do not
        # pay for or risk failing on a verifier command run.
        diagnostics["relevant_paths"] = []
        diagnostics["exemptions"] = []
        diagnostics["ok"] = True
        diagnostics["errors"] = []
        json.dump(diagnostics, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    # ---- Validate and normalize exemptions against this candidate. --------- #
    normalized_exemptions: set[str] = set()
    exemption_errors: list[str] = []
    for entry in manifest.verified_noop:
        normalized, error = _validate_exemption(entry["path"])
        if error is not None:
            exemption_errors.append(f"invalid verified_noop entry: {error}")
            continue
        if normalized in normalized_exemptions:
            exemption_errors.append(f"duplicate verified_noop entry: {normalized!r}")
            continue
        exists_on_disk = (candidate / normalized).exists()
        if not exists_on_disk and normalized not in deleted_paths:
            exemption_errors.append(
                f"verified_noop path does not exist in the candidate or its "
                f"deletion side: {normalized!r}"
            )
            continue
        normalized_exemptions.add(normalized)
    if exemption_errors:
        return _fail(diagnostics, exemption_errors)

    used_exemptions = sorted(p for p in union if p in normalized_exemptions)
    diagnostics["exemptions"] = used_exemptions
    relevant = [p for p in union if p not in normalized_exemptions]
    diagnostics["relevant_paths"] = relevant

    # ---- Run the verifier command in the candidate worktree. --------------- #
    timeout_seconds: float | None = None
    if args.timeout:
        try:
            timeout_seconds = float(args.timeout)
        except ValueError:
            return _fail(diagnostics, [f"invalid --timeout value: {args.timeout!r}"])

    try:
        # A plain `subprocess.run(..., timeout=...)` only kills the verifier
        # command itself; a gate that backgrounds work (`sleep 30 &`) keeps
        # running -- and can keep mutating the candidate -- after this helper
        # has already reported a timeout and landing has stopped.
        # `start_new_session=True` puts the command and anything it spawns in
        # their own process group, so a timeout can reach all of it.
        popen = subprocess.Popen(
            list(manifest.command),
            cwd=str(candidate),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return _fail(diagnostics, [f"verifier command not found: {exc}"])

    try:
        stdout, stderr = popen.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(popen.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        popen.communicate()  # reap; the group is dead so this cannot hang
        return _fail(diagnostics, ["verifier command timed out"])
    proc = subprocess.CompletedProcess(
        list(manifest.command), popen.returncode, stdout, stderr
    )

    if proc.returncode != 0:
        return _fail(
            diagnostics,
            [f"verifier command exited {proc.returncode}: {proc.stderr.strip()[:500]}"],
        )

    result_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not result_lines:
        return _fail(diagnostics, ["verifier command produced no JSON result line"])
    try:
        result = json.loads(result_lines[-1])
    except ValueError as exc:
        return _fail(diagnostics, [f"verifier result is not valid JSON: {exc}"])

    if not isinstance(result, dict):
        return _fail(diagnostics, ["verifier result must be a JSON object"])
    if result.get("schema_version") != lifecycle_extensions.VERIFIER_SCHEMA_VERSION:
        return _fail(
            diagnostics,
            [f"verifier result schema_version must be {lifecycle_extensions.VERIFIER_SCHEMA_VERSION}"],
        )

    status = result.get("status")
    diagnostics["verifier_status"] = status if isinstance(status, str) else None
    if status != "passed":
        return _fail(diagnostics, [f"verifier status is not 'passed': {status!r}"])

    selected_checks = result.get("selected_checks")
    if not isinstance(selected_checks, list):
        return _fail(diagnostics, ["verifier selected_checks must be a list"])

    passed_checks = 0
    for index, check in enumerate(selected_checks):
        if not isinstance(check, dict):
            return _fail(diagnostics, [f"selected_checks[{index}] must be an object"])
        check_status = check.get("status")
        if check_status != "passed":
            return _fail(
                diagnostics,
                [f"selected check {check.get('name')!r} did not pass: {check_status!r}"],
            )
        passed_checks += 1
    diagnostics["selected_check_count"] = passed_checks

    # ---- Apply the fixed precedence. --------------------------------------- #
    if relevant and passed_checks == 0:
        diagnostics["unverified_paths"] = relevant
        return _fail(
            diagnostics,
            [
                "verifier passed with zero selected checks but the candidate has "
                f"{len(relevant)} unverified relevant path(s)"
            ],
        )

    diagnostics["ok"] = True
    diagnostics["errors"] = []
    json.dump(diagnostics, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
