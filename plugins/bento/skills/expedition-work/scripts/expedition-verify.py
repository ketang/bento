#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expedition_state import ExpeditionStateError, current_branch, locate_expedition
from git_state import detect_checkout_root, is_linked_worktree


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expedition", required=True, help="expedition name")
    parser.add_argument("--require-base-worktree", action="store_true", help="fail unless the current checkout is the base worktree")
    parser.add_argument("--require-active-task", action="store_true", help="fail unless the current checkout is the active task worktree")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    try:
        state_file, state = locate_expedition(checkout_root, args.expedition)
    except ExpeditionStateError as exc:
        json.dump({"ok": False, "errors": [str(exc)]}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    base_worktree = Path(str(state["base_worktree"])).resolve()
    active = state.get("active_task")
    active_worktree = Path(str(active["worktree"])).resolve() if active else None
    branch = current_branch(cwd)
    role = "other"
    errors: list[str] = []

    if cwd == base_worktree and branch == state["base_branch"]:
        role = "base"
    elif active and cwd == active_worktree and branch == active["branch"]:
        role = "active_task"
    else:
        errors.append("current checkout does not match the expedition base worktree or active task worktree")

    if args.require_base_worktree and role != "base":
        errors.append("current checkout is not the expedition base worktree")
    if args.require_active_task and role != "active_task":
        errors.append("current checkout is not the active expedition task worktree")

    payload = {
        "ok": not errors,
        "checkout_root": str(checkout_root),
        "state_file": str(state_file),
        "branch": branch,
        "cwd": str(cwd),
        "linked_worktree": is_linked_worktree(cwd),
        "current_role": role,
        "base_worktree": str(base_worktree),
        "active_task_worktree": str(active_worktree) if active_worktree else None,
        "errors": errors,
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
