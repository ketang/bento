#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from git_state import detect_checkout_root, git_stdout, is_linked_worktree, primary_checkout_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-branch", help="required current branch")
    parser.add_argument("--expected-worktree", help="required checkout root path")
    parser.add_argument(
        "--require-linked-worktree",
        action="store_true",
        help="fail if the current checkout is the primary checkout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    branch = git_stdout("branch", "--show-current", cwd=checkout_root)
    linked_worktree = is_linked_worktree(checkout_root)
    expected_worktree = Path(args.expected_worktree).resolve() if args.expected_worktree else None

    checks = {
        "cwd": str(cwd),
        "checkout_root": str(checkout_root),
        "primary_checkout_root": str(primary_checkout_root(checkout_root)),
        "branch": branch,
        "linked_worktree": linked_worktree,
        "current_checkout_is_primary": not linked_worktree,
        "expected_branch_match": args.expected_branch is None or branch == args.expected_branch,
        "expected_worktree_match": expected_worktree is None or checkout_root == expected_worktree,
        "require_linked_worktree_satisfied": not args.require_linked_worktree or linked_worktree,
    }
    checks["ok"] = all(
        [
            checks["expected_branch_match"],
            checks["expected_worktree_match"],
            checks["require_linked_worktree_satisfied"],
        ]
    )

    json.dump(checks, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if checks["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
