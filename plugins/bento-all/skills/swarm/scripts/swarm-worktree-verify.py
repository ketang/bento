#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-branch")
    parser.add_argument("--expected-worktree")
    parser.add_argument("--require-worktree", action="store_true")
    args = parser.parse_args()

    cwd = Path.cwd().resolve()
    repo_root = Path(git("rev-parse", "--show-toplevel")).resolve()
    branch = git("branch", "--show-current")
    in_worktree = ".claude/worktrees/" in str(cwd) or ".codex/worktrees/" in str(cwd)

    checks = {
        "cwd": str(cwd),
        "repo_root": str(repo_root),
        "branch": branch,
        "in_worktree": in_worktree,
        "expected_branch_match": args.expected_branch is None or branch == args.expected_branch,
        "expected_worktree_match": args.expected_worktree is None
        or str(cwd) == str(Path(args.expected_worktree).resolve()),
        "require_worktree_satisfied": not args.require_worktree or in_worktree,
    }
    checks["ok"] = all(
        [
            checks["expected_branch_match"],
            checks["expected_worktree_match"],
            checks["require_worktree_satisfied"],
        ]
    )

    json.dump(checks, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if checks["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
