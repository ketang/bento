#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from expedition_state import ExpeditionStateError, commit_expedition_docs, expedition_dir, locate_expedition
from git_state import detect_checkout_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expedition", required=True, help="expedition name")
    parser.add_argument("--apply", action="store_true", help="remove the branch-local expedition docs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    try:
        state_file, state = locate_expedition(checkout_root, args.expedition)
    except ExpeditionStateError as exc:
        json.dump({"ok": False, "errors": [str(exc)], "updated": False, "docs_removed": False}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

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
        json.dump({"ok": False, "errors": errors, "updated": False, "docs_removed": False}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    updated = False
    docs_removed = False
    if args.apply:
        shutil.rmtree(docs_dir)
        try:
            commit_expedition_docs(
                cwd,
                str(state["expedition"]),
                f"docs(expedition): remove {state['expedition']} expedition state",
            )
        except ExpeditionStateError as exc:
            json.dump({"ok": False, "errors": [str(exc)], "updated": False, "docs_removed": False}, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 1
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
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
