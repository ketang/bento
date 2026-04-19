#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expedition_state import discover_expeditions, handoff_path
from git_state import detect_checkout_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expedition", help="optional expedition name filter")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    expeditions = []

    for state_file, state in discover_expeditions(checkout_root, args.expedition):
        active = state.get("active_task")
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
                "active_task_branch": active["branch"] if active else None,
                "active_task_worktree": active["worktree"] if active else None,
                "current_checkout": str(cwd) in {str(base_worktree), str(Path(active["worktree"]).resolve()) if active else ""},
            }
        )

    payload = {
        "ok": True,
        "checkout_root": str(checkout_root),
        "expeditions": sorted(expeditions, key=lambda item: item["expedition"]),
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
