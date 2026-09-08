#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from git_state import (
    NotAWorkTreeError,
    ahead_behind,
    current_branch,
    detect_checkout_root,
    detect_primary_branch,
    is_bare_repository,
    is_linked_worktree,
    primary_checkout_root,
    ref_exists,
    working_tree_dirty,
)


def _primary_divergence(
    primary_root: Path, primary_branch: str
) -> tuple[str | None, int | None, int | None]:
    """(status, ahead, behind) of the primary checkout's local branch against
    its leased origin ref -- the same ref land-work-verify-lease.py checks.
    None/None/None when either ref is unavailable (e.g. no remote configured),
    since divergence cannot be judged without both sides."""
    remote_ref = f"refs/remotes/origin/{primary_branch}"
    local_ref = f"refs/heads/{primary_branch}"
    if not ref_exists(remote_ref, primary_root) or not ref_exists(local_ref, primary_root):
        return None, None, None
    behind, ahead = ahead_behind(remote_ref, local_ref, primary_root)
    if ahead and behind:
        status = "diverged"
    elif ahead:
        status = "ahead"
    elif behind:
        status = "behind"
    else:
        status = "equal"
    return status, ahead, behind


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-branch", help="required current feature branch name")
    parser.add_argument(
        "--require-linked-worktree",
        action="store_true",
        help="fail if the current checkout is the primary checkout",
    )
    parser.add_argument(
        "--require-up-to-date",
        action="store_true",
        help="fail if the current branch is behind the primary branch",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    branch = current_branch(checkout_root)
    primary_branch, warnings = detect_primary_branch(checkout_root)
    linked_worktree = is_linked_worktree(checkout_root)
    dirty = working_tree_dirty(checkout_root)

    remote_primary_ref = f"refs/remotes/origin/{primary_branch}"
    preferred_rebase_base = (
        f"origin/{primary_branch}" if ref_exists(remote_primary_ref, checkout_root) else primary_branch
    )
    behind_primary, ahead_primary = ahead_behind(primary_branch, branch, checkout_root)

    primary_root = primary_checkout_root(checkout_root)
    primary_bare = is_bare_repository(primary_root)
    # `git status` itself fails ("must be run in a work tree") on a bare
    # checkout, so the dirty check only makes sense once bare is ruled out.
    # Reuse the feature-worktree's own dirty result when it *is* the primary
    # (running land-work-prepare.py directly from the primary checkout)
    # instead of issuing an identical `git status` a second time.
    if primary_bare:
        primary_dirty = None
    elif primary_root == checkout_root:
        primary_dirty = dirty
    else:
        primary_dirty = working_tree_dirty(primary_root)
    if primary_bare:
        primary_local_vs_remote, primary_ahead, primary_behind = None, None, None
    else:
        primary_local_vs_remote, primary_ahead, primary_behind = _primary_divergence(
            primary_root, primary_branch
        )

    errors: list[str] = []
    if args.expected_branch and branch != args.expected_branch:
        errors.append(f"current branch does not match expected branch: {branch}")
    if branch == primary_branch:
        errors.append("current branch is the primary branch; land-work must run from a feature branch")
    if args.require_linked_worktree and not linked_worktree:
        errors.append("current checkout is not a linked worktree")
    if dirty:
        errors.append("working tree is dirty")
    if ahead_primary == 0:
        errors.append("current branch has no commits ahead of the primary branch")
    if args.require_up_to_date and behind_primary != 0:
        errors.append(f"current branch is behind the primary branch by {behind_primary} commit(s)")
    if primary_bare:
        errors.append(
            f"primary checkout at {primary_root} has core.bare=true with a working "
            "tree -- git commands there fail with \"must be run in a work tree\"; "
            "unset core.bare or run from a linked worktree"
        )
    elif primary_dirty:
        errors.append(
            f"primary checkout at {primary_root} has uncommitted changes; commit, "
            "stash, or clean it before landing"
        )

    payload = {
        "cwd": str(cwd),
        "checkout_root": str(checkout_root),
        "primary_checkout_root": str(primary_root),
        "branch": branch,
        "primary_branch": primary_branch,
        "linked_worktree": linked_worktree,
        "working_tree_dirty": dirty,
        "preferred_rebase_base": preferred_rebase_base,
        "remote_primary_ref_available": ref_exists(remote_primary_ref, checkout_root),
        "ahead_of_primary": ahead_primary,
        "behind_primary": behind_primary,
        "expected_branch_match": args.expected_branch is None or branch == args.expected_branch,
        "require_linked_worktree_satisfied": not args.require_linked_worktree or linked_worktree,
        "require_up_to_date_satisfied": not args.require_up_to_date or behind_primary == 0,
        "primary_bare": primary_bare,
        "primary_dirty": primary_dirty,
        "primary_local_vs_remote": primary_local_vs_remote,
        "primary_ahead": primary_ahead,
        "primary_behind": primary_behind,
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
    }

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
