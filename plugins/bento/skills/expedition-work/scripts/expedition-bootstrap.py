#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expedition_state import (
    append_log_entry,
    commit_expedition_docs,
    expedition_dir,
    handoff_path,
    init_state,
    log_path,
    plan_path,
    render_handoff,
    render_log,
    render_plan,
    state_path,
    validate_name,
    write_state,
)
from git_state import detect_checkout_root, detect_primary_branch, git, parse_worktrees


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expedition", required=True, help="expedition name; also used as the base branch name")
    parser.add_argument("--worktree", required=True, help="linked worktree path for the expedition base branch")
    parser.add_argument("--primary-branch", help="override the detected primary branch")
    parser.add_argument("--apply", action="store_true", help="create the worktree and expedition files")
    return parser.parse_args()


def evaluate(args: argparse.Namespace, cwd: Path) -> dict[str, object]:
    checkout_root = detect_checkout_root(cwd)
    detected_primary, warnings = detect_primary_branch(checkout_root)
    primary_branch = args.primary_branch or detected_primary
    expedition = validate_name(args.expedition)
    target_worktree = Path(args.worktree).resolve()
    worktrees = parse_worktrees(checkout_root)

    errors: list[str] = []
    if git("show-ref", "--verify", f"refs/heads/{primary_branch}", cwd=checkout_root, check=False).returncode != 0:
        errors.append(f"primary branch does not exist locally: {primary_branch}")
    if git("show-ref", "--verify", f"refs/heads/{expedition}", cwd=checkout_root, check=False).returncode == 0:
        errors.append(f"expedition base branch already exists locally: {expedition}")
    if target_worktree.exists():
        errors.append(f"target worktree path already exists: {target_worktree}")
    if str(target_worktree) in {str(worktree['path']) for worktree in worktrees}:
        errors.append(f"target worktree path is already registered: {target_worktree}")

    return {
        "checkout_root": str(checkout_root),
        "primary_branch": primary_branch,
        "target_branch": expedition,
        "target_worktree": str(target_worktree),
        "warnings": warnings,
        "errors": errors,
        "ok": not errors,
        "apply_mode": args.apply,
    }


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    result = evaluate(args, cwd)

    if args.apply and not result["ok"]:
        json.dump({**result, "created": False}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    created = False
    docs_created = False
    if args.apply:
        checkout_root = Path(str(result["checkout_root"]))
        target_worktree = Path(str(result["target_worktree"]))
        branch = str(result["target_branch"])
        primary_branch = str(result["primary_branch"])

        worktree_result = git(
            "worktree",
            "add",
            "-b",
            branch,
            str(target_worktree),
            primary_branch,
            cwd=checkout_root,
            check=False,
        )
        if worktree_result.returncode != 0:
            payload = {**result, "created": False, "errors": [*result["errors"], worktree_result.stderr.strip()]}
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return worktree_result.returncode

        created = True
        docs_root = expedition_dir(target_worktree, branch)
        docs_root.mkdir(parents=True, exist_ok=True)

        state = init_state(
            expedition=branch,
            primary_branch=primary_branch,
            base_worktree=target_worktree,
        )
        write_state(state_path(target_worktree, branch), state)
        plan_path(target_worktree, branch).write_text(render_plan(state), encoding="utf-8")
        log_path(target_worktree, branch).write_text(render_log(state), encoding="utf-8")
        handoff_path(target_worktree, branch).write_text(render_handoff(state), encoding="utf-8")
        append_log_entry(
            log_path(target_worktree, branch),
            "Expedition initialized",
            [
                f"Base branch `{branch}` created from `{primary_branch}`.",
                f"Base worktree: `{target_worktree}`.",
                "Next action: create the first serial task branch.",
            ],
        )
        commit_expedition_docs(
            target_worktree,
            branch,
            f"docs(expedition): initialize {branch} expedition",
        )
        docs_created = True

    json.dump({**result, "created": created, "docs_created": docs_created}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
