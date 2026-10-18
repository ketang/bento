#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from git_state import (
    NotAWorkTreeError,
    detect_checkout_root,
    git_stdout,
    is_linked_worktree,
    primary_checkout_root,
    try_git_stdout,
)


def parse_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--worktree-dir",
        help="evaluate this checkout instead of the process cwd (cwd-safe invocation)",
    )
    parser.add_argument("--expected-branch", help="required current branch")
    parser.add_argument("--expected-worktree", help="required checkout root path")
    parser.add_argument(
        "--require-linked-worktree",
        action="store_true",
        help="fail if the current checkout is the primary checkout",
    )
    return parser, parser.parse_args()


def build_errors(checks: dict, args, expected_worktree, require_linked: bool, used_worktree_dir: bool) -> list[str]:
    errors: list[str] = []
    root = checks["checkout_root"]
    target = str(expected_worktree) if expected_worktree else "<expected-worktree>"
    if not checks["expected_worktree_match"] or (require_linked and not checks["linked_worktree"]):
        where = "primary checkout" if checks["current_checkout_is_primary"] else "checkout"
        msg = f"current {where} is {root}"
        if expected_worktree:
            msg += f", expected {expected_worktree}"
        if used_worktree_dir:
            msg += f"; --worktree-dir does not point at the intended worktree: pass --worktree-dir {target}"
        else:
            msg += f"; re-run with --worktree-dir {target} or cd {target} && <same command>"
        errors.append(msg)
    if not checks["expected_branch_match"]:
        errors.append(f"branch {checks['branch']!r} != expected {args.expected_branch!r}")
    return errors


def main() -> int:
    parser, args = parse_args()
    cwd = Path.cwd().resolve()
    if args.worktree_dir:
        cwd = Path(args.worktree_dir).resolve()
        if not cwd.is_dir() or try_git_stdout("rev-parse", "--git-dir", cwd=cwd) is None:
            parser.error(f"--worktree-dir {args.worktree_dir} is not inside a git checkout")
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

    errors = build_errors(checks, args, expected_worktree, args.require_linked_worktree, bool(args.worktree_dir))
    if errors:
        checks["errors"] = errors

    json.dump(checks, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if checks["ok"] else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except NotAWorkTreeError as exc:
        json.dump(exc.diagnostic, sys.stdout, indent=2)
        sys.stdout.write("\n")
        exit_code = 1
    raise SystemExit(exit_code)
