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
    is_clean,
    locate_expedition,
    sync_markdown_views,
    utc_now,
    write_state,
)
from git_state import detect_checkout_root, git


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expedition", required=True, help="expedition name")
    parser.add_argument("--outcome", choices=("kept", "failed-experiment"), required=True)
    parser.add_argument("--summary", required=True, help="short summary of the task result")
    parser.add_argument("--apply", action="store_true", help="apply merge/rebase and update expedition state")
    return parser.parse_args()


def evaluate(args: argparse.Namespace, cwd: Path) -> tuple[dict[str, object], dict[str, object]]:
    checkout_root = detect_checkout_root(cwd)
    state_file, state = locate_expedition(checkout_root, args.expedition)
    base_worktree = Path(str(state["base_worktree"])).resolve()
    active = state.get("active_task")

    errors: list[str] = []
    if cwd.resolve() != base_worktree:
        errors.append(f"close-task must run from the expedition base worktree: {base_worktree}")
    if current_branch(cwd) != state["base_branch"]:
        errors.append(f"current branch does not match the expedition base branch: {state['base_branch']}")
    if active is None:
        errors.append("expedition has no active task to close")
    elif args.outcome == "failed-experiment" and active["kind"] != "experiment":
        errors.append("failed-experiment outcome is only valid for experiment branches")
    if not is_clean(cwd):
        errors.append("expedition base worktree is dirty; close-task expects a clean base worktree before merge/rebase")
    if active and args.outcome == "kept":
        task_worktree = Path(str(active["worktree"])).resolve()
        if not task_worktree.exists():
            errors.append(f"active task worktree is missing: {task_worktree}")
        elif not is_clean(task_worktree):
            errors.append("kept tasks must be committed before close-task runs")

    return (
        {
            "checkout_root": str(checkout_root),
            "state_file": str(state_file),
            "expedition": state["expedition"],
            "outcome": args.outcome,
            "summary": args.summary,
            "active_task_branch": active["branch"] if active else None,
            "errors": errors,
            "ok": not errors,
            "apply_mode": args.apply,
        },
        state,
    )


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    try:
        result, state = evaluate(args, cwd)
    except ExpeditionStateError as exc:
        json.dump({"ok": False, "errors": [str(exc)], "updated": False, "merged": False, "rebased": False}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    if args.apply and not result["ok"]:
        json.dump({**result, "updated": False, "merged": False, "rebased": False}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    merged = False
    rebased = False
    updated = False
    if args.apply:
        active = state["active_task"]
        state_file = Path(str(result["state_file"]))
        task_branch = str(active["branch"])

        if args.outcome == "kept":
            merge_result = git(
                "merge",
                "--no-ff",
                task_branch,
                "-m",
                f"Merge branch '{task_branch}'",
                cwd=cwd,
                check=False,
            )
            if merge_result.returncode != 0:
                payload = {**result, "updated": False, "merged": False, "rebased": False, "errors": [merge_result.stderr.strip()]}
                json.dump(payload, sys.stdout, indent=2)
                sys.stdout.write("\n")
                return merge_result.returncode
            merged = True

            rebase_result = git("rebase", str(state["primary_branch"]), cwd=cwd, check=False)
            if rebase_result.returncode != 0:
                payload = {
                    **result,
                    "updated": False,
                    "merged": merged,
                    "rebased": False,
                    "errors": [rebase_result.stderr.strip()],
                }
                json.dump(payload, sys.stdout, indent=2)
                sys.stdout.write("\n")
                return rebase_result.returncode
            rebased = True

        completion = {
            "number": active["number"],
            "kind": active["kind"],
            "slug": active["slug"],
            "branch": active["branch"],
            "worktree": active["worktree"],
            "outcome": args.outcome,
            "summary": args.summary,
            "completed_at": utc_now(),
        }
        if args.outcome == "failed-experiment":
            state["preserved_experiments"].append(completion)

        state["last_completed"] = completion
        state["active_task"] = None
        state["next_task_number"] = int(active["number"]) + 1
        state["updated_at"] = utc_now()
        state["status"] = "ready_for_task"
        if rebased:
            state["next_action"] = "Create the next task branch from the rebased expedition base branch."
        else:
            state["next_action"] = "Create the next task branch from the expedition base branch."
        write_state(state_file, state)
        append_log_entry(
            cwd / "docs" / "expeditions" / str(state["expedition"]) / "log.md",
            f"Closed {active['kind']}",
            [
                f"Branch: `{active['branch']}`.",
                f"Outcome: `{args.outcome}`.",
                f"Summary: {args.summary}",
                "Base branch rebased onto the primary branch." if rebased else "Experiment preserved without merging.",
            ],
        )
        sync_markdown_views(cwd, state)
        commit_expedition_docs(
            cwd,
            str(state["expedition"]),
            f"log(expedition): close {active['branch']} ({args.outcome})",
        )
        updated = True

    json.dump({**result, "updated": updated, "merged": merged, "rebased": rebased}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
