#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from expedition_state import (
    ExpeditionStateError,
    append_log_entry,
    commit_expedition_docs,
    current_branch,
    current_head,
    discover_expeditions,
    expedition_dir,
    handoff_path,
    init_state,
    is_clean,
    locate_expedition,
    log_path,
    next_branch_name,
    next_worktree_path,
    plan_path,
    render_handoff,
    render_log,
    render_plan,
    slugify,
    state_path,
    sync_markdown_views,
    utc_now,
    validate_name,
    write_state,
)
from git_state import (
    detect_checkout_root,
    detect_primary_branch,
    git,
    is_linked_worktree,
    parse_worktrees,
    ref_exists,
)


def _emit(payload: dict[str, object], rc: int = 0) -> int:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return rc


def _bootstrap_evaluate(args: argparse.Namespace, cwd: Path) -> dict[str, object]:
    checkout_root = detect_checkout_root(cwd)
    detected_primary, warnings = detect_primary_branch(checkout_root)
    primary_branch = args.primary_branch or detected_primary
    expedition = validate_name(args.expedition)
    target_worktree = Path(args.worktree).resolve()
    worktrees = parse_worktrees(checkout_root)

    errors: list[str] = []
    if not ref_exists(f"refs/heads/{primary_branch}", cwd=checkout_root):
        errors.append(f"primary branch does not exist locally: {primary_branch}")
    if ref_exists(f"refs/heads/{expedition}", cwd=checkout_root):
        errors.append(f"expedition base branch already exists locally: {expedition}")
    if target_worktree.exists():
        errors.append(f"target worktree path already exists: {target_worktree}")
    if str(target_worktree) in {str(worktree["path"]) for worktree in worktrees}:
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


def cmd_bootstrap(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    result = _bootstrap_evaluate(args, cwd)

    if args.apply and not result["ok"]:
        return _emit({**result, "created": False}, 1)

    created = False
    docs_created = False
    if args.apply:
        checkout_root = Path(str(result["checkout_root"]))
        target_worktree = Path(str(result["target_worktree"]))
        branch = str(result["target_branch"])
        primary_branch = str(result["primary_branch"])

        worktree_result = git(
            "worktree", "add", "-b", branch, str(target_worktree), primary_branch,
            cwd=checkout_root, check=False,
        )
        if worktree_result.returncode != 0:
            payload = {**result, "created": False, "errors": [*result["errors"], worktree_result.stderr.strip()]}
            return _emit(payload, worktree_result.returncode)

        created = True
        expedition_dir(target_worktree, branch).mkdir(parents=True, exist_ok=True)

        state = init_state(expedition=branch, primary_branch=primary_branch, base_worktree=target_worktree)
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
        commit_expedition_docs(target_worktree, branch, f"docs(expedition): initialize {branch} expedition")
        docs_created = True

    return _emit({**result, "created": created, "docs_created": docs_created})


def cmd_discover(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    expeditions = []

    for state_file, state in discover_expeditions(checkout_root, args.expedition):
        active_list = state.get("active_branches") or []
        first_active = active_list[0] if active_list else None
        base_worktree = Path(str(state["base_worktree"])).resolve()
        expeditions.append(
            {
                "expedition": state["expedition"],
                "base_branch": state["base_branch"],
                "base_worktree": str(base_worktree),
                "state_file": str(state_file),
                "handoff_file": str(handoff_path(base_worktree, str(state["expedition"]))),
                "status": state["status"],
                "next_action": state["next_action"],
                "active_task_branch": first_active["branch"] if first_active else None,
                "active_task_worktree": first_active["worktree"] if first_active else None,
                "current_checkout": str(cwd) in {
                    str(base_worktree),
                    str(Path(first_active["worktree"]).resolve()) if first_active else "",
                },
            }
        )

    return _emit({
        "ok": True,
        "checkout_root": str(checkout_root),
        "expeditions": sorted(expeditions, key=lambda item: item["expedition"]),
    })


def _start_task_evaluate(
    args: argparse.Namespace, cwd: Path
) -> tuple[dict[str, object], dict[str, object]]:
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
    if ref_exists(f"refs/heads/{branch}", cwd=checkout_root):
        errors.append(f"target task branch already exists locally: {branch}")
    if target_worktree.exists():
        errors.append(f"target worktree path already exists: {target_worktree}")
    if str(target_worktree) in {str(worktree["path"]) for worktree in worktrees}:
        errors.append(f"target worktree path is already registered: {target_worktree}")

    return (
        {
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
        },
        state,
    )


def cmd_start_task(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    try:
        result, state = _start_task_evaluate(args, cwd)
    except ExpeditionStateError as exc:
        return _emit({"ok": False, "errors": [str(exc)], "created": False}, 1)

    if args.apply and not result["ok"]:
        return _emit({**result, "created": False}, 1)

    created = False
    if args.apply:
        checkout_root = Path(str(result["checkout_root"]))
        state_file = Path(str(result["state_file"]))
        branch = str(result["target_branch"])
        target_worktree = Path(str(result["target_worktree"]))

        worktree_result = git(
            "worktree", "add", "-b", branch, str(target_worktree), str(state["base_branch"]),
            cwd=checkout_root, check=False,
        )
        if worktree_result.returncode != 0:
            payload = {**result, "created": False, "errors": [*result["errors"], worktree_result.stderr.strip()]}
            return _emit(payload, worktree_result.returncode)

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
            log_path(cwd, str(state["expedition"])),
            f"Started {result['kind']}",
            [
                f"Branch: `{branch}`.",
                f"Worktree: `{target_worktree}`.",
                f"Base head at branch creation: `{active_task['base_head']}`.",
            ],
        )
        sync_markdown_views(cwd, state)
        commit_expedition_docs(cwd, str(state["expedition"]), f"log(expedition): start {branch}")

    return _emit({**result, "created": created})


def _close_task_evaluate(
    args: argparse.Namespace, cwd: Path
) -> tuple[dict[str, object], dict[str, object]]:
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


def cmd_close_task(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    try:
        result, state = _close_task_evaluate(args, cwd)
    except ExpeditionStateError as exc:
        return _emit({"ok": False, "errors": [str(exc)], "updated": False, "merged": False, "rebased": False}, 1)

    if args.apply and not result["ok"]:
        return _emit({**result, "updated": False, "merged": False, "rebased": False}, 1)

    merged = False
    rebased = False
    updated = False
    if args.apply:
        active = state["active_task"]
        state_file = Path(str(result["state_file"]))
        task_branch = str(active["branch"])

        if args.outcome == "kept":
            merge_result = git(
                "merge", "--no-ff", task_branch, "-m", f"Merge branch '{task_branch}'",
                cwd=cwd, check=False,
            )
            if merge_result.returncode != 0:
                payload = {**result, "updated": False, "merged": False, "rebased": False, "errors": [merge_result.stderr.strip()]}
                return _emit(payload, merge_result.returncode)
            merged = True

            rebase_result = git("rebase", str(state["primary_branch"]), cwd=cwd, check=False)
            if rebase_result.returncode != 0:
                payload = {**result, "updated": False, "merged": merged, "rebased": False, "errors": [rebase_result.stderr.strip()]}
                return _emit(payload, rebase_result.returncode)
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
        state["next_action"] = (
            "Create the next task branch from the rebased expedition base branch."
            if rebased
            else "Create the next task branch from the expedition base branch."
        )
        write_state(state_file, state)
        append_log_entry(
            log_path(cwd, str(state["expedition"])),
            f"Closed {active['kind']}",
            [
                f"Branch: `{active['branch']}`.",
                f"Outcome: `{args.outcome}`.",
                f"Summary: {args.summary}",
                "Base branch rebased onto the primary branch." if rebased else "Experiment preserved without merging.",
            ],
        )
        sync_markdown_views(cwd, state)
        commit_expedition_docs(cwd, str(state["expedition"]), f"log(expedition): close {active['branch']} ({args.outcome})")
        updated = True

    return _emit({**result, "updated": updated, "merged": merged, "rebased": rebased})


def cmd_finish(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    try:
        state_file, state = locate_expedition(checkout_root, args.expedition)
    except ExpeditionStateError as exc:
        return _emit({"ok": False, "errors": [str(exc)], "updated": False, "docs_removed": False}, 1)

    base_worktree = Path(str(state["base_worktree"])).resolve()
    docs_dir = expedition_dir(base_worktree, str(state["expedition"]))
    errors: list[str] = []
    if cwd != base_worktree:
        errors.append(f"finish must run from the expedition base worktree: {base_worktree}")
    if state.get("active_task") is not None:
        errors.append("finish cannot run while an expedition task is still active")
    if not docs_dir.exists():
        errors.append(f"expedition docs directory is missing: {docs_dir}")

    if args.apply and errors:
        return _emit({"ok": False, "errors": errors, "updated": False, "docs_removed": False}, 1)

    updated = False
    docs_removed = False
    if args.apply:
        shutil.rmtree(docs_dir)
        try:
            commit_expedition_docs(cwd, str(state["expedition"]), f"docs(expedition): remove {state['expedition']} expedition state")
        except ExpeditionStateError as exc:
            return _emit({"ok": False, "errors": [str(exc)], "updated": False, "docs_removed": False}, 1)
        updated = True
        docs_removed = True

    payload = {
        "ok": not errors,
        "checkout_root": str(checkout_root),
        "state_file": str(state_file),
        "expedition": state["expedition"],
        "base_branch": state["base_branch"],
        "base_worktree": str(base_worktree),
        "updated": updated,
        "docs_removed": docs_removed,
        "next_action": "Run the final verification gates, commit the expedition-doc removal, and land the rebased base branch onto the primary branch.",
        "errors": errors,
    }
    return _emit(payload, 0 if payload["ok"] else 1)


def cmd_verify(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    try:
        state_file, state = locate_expedition(checkout_root, args.expedition)
    except ExpeditionStateError as exc:
        return _emit({"ok": False, "errors": [str(exc)]}, 1)

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
    return _emit(payload, 0 if payload["ok"] else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expedition",
        description="Expedition workflow management",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="create the expedition base branch and worktree")
    p.add_argument("--expedition", required=True, help="expedition name; also used as the base branch name")
    p.add_argument("--worktree", required=True, help="linked worktree path for the expedition base branch")
    p.add_argument("--primary-branch", help="override the detected primary branch")
    p.add_argument("--apply", action="store_true", help="create the worktree and expedition files")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("discover", help="scan linked worktrees for expedition state")
    p.add_argument("--expedition", help="optional expedition name filter")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("start-task", help="create the next serial task or experiment branch")
    p.add_argument("--expedition", required=True, help="expedition name")
    p.add_argument("--slug", required=True, help="meaningful task slug seed")
    p.add_argument("--kind", choices=("task", "experiment"), default="task",
                   help="whether the next branch is a normal task or an experiment")
    p.add_argument("--apply", action="store_true", help="create the next task branch/worktree and update state")
    p.set_defaults(func=cmd_start_task)

    p = sub.add_parser("close-task", help="merge a kept task or preserve a failed experiment")
    p.add_argument("--expedition", required=True, help="expedition name")
    p.add_argument("--outcome", choices=("kept", "failed-experiment"), required=True)
    p.add_argument("--summary", required=True, help="short summary of the task result")
    p.add_argument("--apply", action="store_true", help="apply merge/rebase and update expedition state")
    p.set_defaults(func=cmd_close_task)

    p = sub.add_parser("finish", help="remove branch-local expedition docs before final landing")
    p.add_argument("--expedition", required=True, help="expedition name")
    p.add_argument("--apply", action="store_true", help="remove the branch-local expedition docs")
    p.set_defaults(func=cmd_finish)

    p = sub.add_parser("verify", help="verify the current checkout matches the expedition context")
    p.add_argument("--expedition", required=True, help="expedition name")
    p.add_argument("--require-base-worktree", action="store_true",
                   help="fail unless the current checkout is the base worktree")
    p.add_argument("--require-active-task", action="store_true",
                   help="fail unless the current checkout is the active task worktree")
    p.set_defaults(func=cmd_verify)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
