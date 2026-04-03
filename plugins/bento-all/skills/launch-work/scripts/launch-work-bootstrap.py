#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from git_state import detect_checkout_root, detect_primary_branch, git, parse_worktrees, primary_checkout_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True, help="target branch name")
    parser.add_argument("--worktree", required=True, help="target linked worktree path")
    parser.add_argument("--base-branch", help="branch to branch from; defaults to detected primary branch")
    parser.add_argument("--apply", action="store_true", help="create the branch and linked worktree")
    return parser.parse_args()


def evaluate(args: argparse.Namespace, cwd: Path) -> dict[str, object]:
    checkout_root = detect_checkout_root(cwd)
    primary_branch, warnings = detect_primary_branch(checkout_root)
    base_branch = args.base_branch or primary_branch
    target_worktree = Path(args.worktree).resolve()
    worktrees = parse_worktrees(checkout_root)
    branch_to_path = {
        str(worktree["branch"]): str(worktree["path"])
        for worktree in worktrees
        if worktree.get("branch")
    }

    errors: list[str] = []
    if git("show-ref", "--verify", f"refs/heads/{base_branch}", cwd=checkout_root, check=False).returncode != 0:
        errors.append(f"base branch does not exist locally: {base_branch}")
    if git("show-ref", "--verify", f"refs/heads/{args.branch}", cwd=checkout_root, check=False).returncode == 0:
        errors.append(f"target branch already exists locally: {args.branch}")
    if args.branch in branch_to_path:
        errors.append(f"target branch is already checked out in a worktree: {branch_to_path[args.branch]}")
    if target_worktree.exists():
        errors.append(f"target worktree path already exists: {target_worktree}")
    if str(target_worktree) in {str(worktree["path"]) for worktree in worktrees}:
        errors.append(f"target worktree path is already registered: {target_worktree}")

    return {
        "checkout_root": str(checkout_root),
        "primary_checkout_root": str(primary_checkout_root(checkout_root)),
        "primary_branch": primary_branch,
        "base_branch": base_branch,
        "target_branch": args.branch,
        "target_worktree": str(target_worktree),
        "existing_worktrees": worktrees,
        "existing_branch_worktrees": branch_to_path,
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
        "apply_mode": args.apply,
    }


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    result = evaluate(args, cwd)
    created = False

    if args.apply and not result["ok"]:
        json.dump({**result, "created": created}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    if args.apply:
        command = [
            "worktree",
            "add",
            "-b",
            str(result["target_branch"]),
            str(result["target_worktree"]),
            str(result["base_branch"]),
        ]
        exec_result = git(*command, cwd=Path(str(result["checkout_root"])), check=False)
        if exec_result.returncode != 0:
            payload = {
                **result,
                "created": created,
                "errors": list(result["errors"]) + [exec_result.stderr.strip() or "git worktree add failed"],
            }
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return exec_result.returncode
        created = True

    json.dump({**result, "created": created}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
