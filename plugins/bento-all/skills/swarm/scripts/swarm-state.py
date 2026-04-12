#!/usr/bin/env python3

import argparse
import json
import os
import sys
from pathlib import Path

from git_state import detect_checkout_root


SWARM_STATE_DIR = ".agent-state"
SWARM_SKILL_DIR = "swarm"
CODEX_RUNTIME_DIR = "codex"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        choices=("codex",),
        default="codex",
        help="Resolve runtime-local swarm state for the selected runtime.",
    )
    parser.add_argument(
        "--thread-id",
        help="Override the Codex thread ID instead of reading CODEX_THREAD_ID from the environment.",
    )
    return parser.parse_args()


def codex_thread_id(args: argparse.Namespace) -> str:
    thread_id = args.thread_id or os.environ.get("CODEX_THREAD_ID")
    if thread_id:
        return thread_id
    raise ValueError("CODEX_THREAD_ID is required for Codex swarm state")


def codex_state(thread_id: str) -> dict[str, object]:
    checkout_root = detect_checkout_root(Path.cwd())
    state_root = checkout_root / SWARM_STATE_DIR / SWARM_SKILL_DIR / CODEX_RUNTIME_DIR / thread_id
    continue_file = state_root / "continue.txt"
    handoff_file = state_root / "handoff.md"
    state_found = state_root.exists()
    return {
        "runtime": "codex",
        "thread_id": thread_id,
        "checkout_root": str(checkout_root),
        "state_root": str(state_root),
        "continue_file": str(continue_file),
        "handoff_file": str(handoff_file),
        "ephemeral": True,
        "state_found": state_found,
        "recompute_required": not state_found,
    }


def main() -> int:
    args = parse_args()
    try:
        payload = codex_state(codex_thread_id(args))
    except ValueError as exc:
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    payload["ok"] = True
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
