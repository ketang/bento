#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import subprocess

from git_state import (
    NotAWorkTreeError,
    current_branch,
    detect_checkout_root,
    detect_primary_branch,
    is_linked_worktree,
    primary_checkout_root,
    ref_exists,
    registered_worktree_paths,
    rev_parse,
    tree_for_ref,
    try_git_stdout,
)

# Same regex pair launch-work-bootstrap.py uses for `--claim auto`, kept in
# sync by convention rather than a shared import (each skill's scripts/ is
# copied standalone into the generated plugin).
_ISSUE_ID_RE = re.compile(r"^([a-z]+-[a-z0-9.]+)")
_ISSUE_SUBISSUE_RE = re.compile(r"^-(\d+)(?:-|$)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", help="ref to verify; defaults to refs/heads/<primary-branch> when available")
    parser.add_argument("--expected-sha", help="required commit SHA for the landed ref")
    parser.add_argument("--expected-tree", help="required tree SHA for the landed ref")
    parser.add_argument(
        "--preview-dir",
        help="preview worktree path that must no longer be registered (i.e. cleaned up) after landing",
    )
    parser.add_argument(
        "--issue",
        metavar="<id|auto>",
        help="warn (never fails) if this tracker issue is not closed after landing. "
        "'auto' takes the leading <prefix>-<id> token of the current branch, same "
        "regex as launch-work-bootstrap.py's --claim auto",
    )
    return parser.parse_args()


def _resolve_issue_id(issue_arg: str, branch: str) -> str | None:
    if issue_arg != "auto":
        return issue_arg
    match = _ISSUE_ID_RE.match(branch)
    if not match:
        return None
    issue_id = match.group(1)
    remainder = branch[match.end():]
    sub_match = _ISSUE_SUBISSUE_RE.match(remainder)
    if sub_match:
        issue_id = f"{issue_id}.{sub_match.group(1)}"
    return issue_id


def _detect_tracker(checkout_root: Path, primary_root: Path) -> str | None:
    if (primary_root / ".beads").is_dir() and shutil.which("bd"):
        return "beads"
    origin_url = try_git_stdout("remote", "get-url", "origin", cwd=checkout_root)
    if origin_url and "github.com" in origin_url and shutil.which("gh"):
        return "github"
    return None


def _check_issue_status(
    issue_arg: str, branch: str, checkout_root: Path, primary_root: Path, warnings: list[str]
) -> str | None:
    """Warn (never raises, never affects the exit code) if the tracker issue
    named by --issue is not closed. A lookup failure is itself a warning."""
    issue_id = _resolve_issue_id(issue_arg, branch)
    if issue_id is None:
        warnings.append(f"--issue auto: branch {branch!r} does not match <prefix>-<id>; skipping issue check")
        return None

    tracker = _detect_tracker(checkout_root, primary_root)
    if tracker is None:
        warnings.append(
            f"--issue {issue_id}: no tracker detected (no .beads/ with bd on "
            "PATH, no GitHub remote with gh on PATH); skipping issue check"
        )
        return None

    if tracker == "beads":
        command = ["bd", "show", issue_id, "--json"]
    else:
        command = ["gh", "issue", "view", issue_id, "--json", "state"]

    try:
        proc = subprocess.run(command, cwd=primary_root, capture_output=True, text=True, check=False)
    except OSError as exc:
        warnings.append(f"issue lookup failed: {' '.join(command)}: {exc}")
        return None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        warnings.append(f"issue lookup failed: {' '.join(command)}: {detail}")
        return None

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        warnings.append(f"issue lookup returned unparseable JSON: {' '.join(command)}")
        return None

    if tracker == "beads":
        if not isinstance(parsed, list) or not parsed:
            warnings.append(f"issue lookup returned no result: {' '.join(command)}")
            return None
        status = parsed[0].get("status")
        if status != "closed":
            warnings.append(
                f"{issue_id} is not closed (status: {status}); run: bd close {issue_id} "
                f'--reason "<sha> landed on <primary-branch>"'
            )
    else:
        status = parsed.get("state")
        if status != "CLOSED":
            warnings.append(f"{issue_id} is not closed (state: {status}); run: gh issue close {issue_id}")
    return status


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    primary_branch, warnings = detect_primary_branch(checkout_root)
    branch = current_branch(checkout_root)
    default_ref = (
        f"refs/heads/{primary_branch}"
        if ref_exists(f"refs/heads/{primary_branch}", checkout_root)
        else f"refs/remotes/origin/{primary_branch}"
    )
    ref = args.ref or default_ref

    errors: list[str] = []
    resolved_sha = None
    resolved_tree = None
    sha_matches = args.expected_sha is None
    tree_matches = args.expected_tree is None

    if not ref_exists(ref, checkout_root):
        errors.append(f"ref does not exist: {ref}")
    else:
        resolved_sha = rev_parse(ref, checkout_root)
        resolved_tree = tree_for_ref(ref, checkout_root)

    if args.expected_sha is not None:
        sha_matches = resolved_sha == args.expected_sha
        if not sha_matches:
            errors.append(f"landed ref mismatch for {ref}")
    if args.expected_tree is not None:
        tree_matches = resolved_tree == args.expected_tree
        if not tree_matches:
            errors.append(f"landed tree mismatch for {ref}")

    preview_dir_registered = None
    if args.preview_dir:
        preview_path = Path(args.preview_dir).resolve()
        try:
            registered = registered_worktree_paths(checkout_root)
        except subprocess.CalledProcessError:
            errors.append(
                f"unable to list registered worktrees in {checkout_root} (`git worktree list` failed)"
            )
        else:
            preview_dir_registered = preview_path in registered
            if preview_dir_registered:
                errors.append(
                    f"preview worktree still registered: {preview_path} (run "
                    f"land-work-create-preview.py --cleanup --preview-dir {preview_path})"
                )

    issue_status = None
    if args.issue is not None:
        primary_root = primary_checkout_root(checkout_root)
        issue_status = _check_issue_status(args.issue, branch, checkout_root, primary_root, warnings)

    payload = {
        "cwd": str(cwd),
        "checkout_root": str(checkout_root),
        "branch": branch,
        "primary_branch": primary_branch,
        "linked_worktree": is_linked_worktree(checkout_root),
        "ref": ref,
        "resolved_sha": resolved_sha,
        "resolved_tree": resolved_tree,
        "expected_sha": args.expected_sha,
        "expected_tree": args.expected_tree,
        "sha_matches": sha_matches,
        "tree_matches": tree_matches,
        "preview_dir": str(args.preview_dir) if args.preview_dir else None,
        "preview_dir_registered": preview_dir_registered,
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
    }
    if args.issue is not None:
        payload["issue_status"] = issue_status

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except NotAWorkTreeError as exc:
        json.dump(exc.diagnostic, sys.stdout, indent=2)
        sys.stdout.write("\n")
        exit_code = 1
    raise SystemExit(exit_code)
