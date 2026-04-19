#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expedition_state import (
    ExpeditionStateError,
    append_log_entry,
    commit_expedition_docs,
    current_branch,
    current_head,
    is_clean,
    locate_expedition,
    next_branch_name,
    next_worktree_path,
    slugify,
    state_path,
    sync_markdown_views,
    utc_now,
    write_state,
)
from git_state import detect_checkout_root, git, is_linked_worktree, parse_worktrees


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expedition", required=True, help="expedition name")
    parser.add_argument("--slug", required=True, help="meaningful task slug seed")
    parser.add_argument(
        "--kind",
        choices=("task", "experiment"),
        default="task",
        help="whether the next branch is a normal task or an experiment",
    )
    parser.add_argument("--apply", action="store_true", help="create the next task branch/worktree and update state")
    return parser.parse_args()


def evaluate(args: argparse.Namespace, cwd: Path) -> dict[str, object]:
    checkout_root = detect_checkout_root(cwd)
    state_file, state = locate_expedition(checkout_root, args.expedition)
    base_worktree = Path(str(state["base_worktree"])).resolve()
    branch = next_branch_name(state, args.kind, slugify(args.slug))
    target_worktree = next_worktree_path(state, branch)
    worktrees = parse_worktrees(checkout_root)

    errors: list[str] = []
    if cwd.resolve() != base_worktree:
        errors.append(f"start-task must run from the expedition base worktree: {base_worktree}")
    if current_branch(cwd) != state["base_branch"]:
        errors.append(f"current branch does not match the expedition base branch: {state['base_branch']}")
    if not is_linked_worktree(cwd):
        errors.append("start-task requires the expedition base checkout to be a linked worktree")
    if state.get("active_task") is not None:
        errors.append(f"expedition already has an active task branch: {state['active_task']['branch']}")
    if not is_clean(cwd):
        errors.append("expedition base worktree is dirty; commit or stash changes before creating the next task")
    if git("show-ref", "--verify", f"refs/heads/{branch}", cwd=checkout_root, check=False).returncode == 0:
        errors.append(f"target task branch already exists locally: {branch}")
    if target_worktree.exists():
        errors.append(f"target worktree path already exists: {target_worktree}")
    if str(target_worktree) in {str(worktree['path']) for worktree in worktrees}:
        errors.append(f"target worktree path is already registered: {target_worktree}")

    return {
        "checkout_root": str(checkout_root),
        "state_file": str(state_file),
        "expedition": state["expedition"],
        "kind": args.kind,
        "target_branch": branch,
        "target_worktree": str(target_worktree),
        "warnings": [],
        "errors": errors,
        "ok": not errors,
        "apply_mode": args.apply,
    }


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    try:
        result = evaluate(args, cwd)
    except ExpeditionStateError as exc:
        json.dump({"ok": False, "errors": [str(exc)], "created": False}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    if args.apply and not result["ok"]:
        json.dump({**result, "created": False}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    created = False
    if args.apply:
        checkout_root = Path(str(result["checkout_root"]))
        state_file = Path(str(result["state_file"]))
        state = json.loads(state_file.read_text(encoding="utf-8"))
        branch = str(result["target_branch"])
        target_worktree = Path(str(result["target_worktree"]))

        worktree_result = git(
            "worktree",
            "add",
            "-b",
            branch,
            str(target_worktree),
            str(state["base_branch"]),
            cwd=checkout_root,
            check=False,
        )
        if worktree_result.returncode != 0:
            payload = {**result, "created": False, "errors": [*result["errors"], worktree_result.stderr.strip()]}
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return worktree_result.returncode

        created = True
        active_task = {
            "number": int(state["next_task_number"]),
            "kind": str(result["kind"]),
            "slug": slugify(args.slug),
            "branch": branch,
            "worktree": str(target_worktree),
            "base_head": current_head(cwd),
            "started_at": utc_now(),
        }
        state["active_task"] = active_task
        state["status"] = "task_in_progress"
        state["updated_at"] = utc_now()
        state["next_action"] = f"Complete work on `{branch}` in `{target_worktree}`."
        write_state(state_file, state)
        append_log_entry(
            cwd / "docs" / "expeditions" / str(state["expedition"]) / "log.md",
            f"Started {result['kind']}",
            [
                f"Branch: `{branch}`.",
                f"Worktree: `{target_worktree}`.",
                f"Base head at branch creation: `{active_task['base_head']}`.",
            ],
        )
        sync_markdown_views(cwd, state)
        commit_expedition_docs(
            cwd,
            str(state["expedition"]),
            f"log(expedition): start {branch}",
        )

    json.dump({**result, "created": created}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
