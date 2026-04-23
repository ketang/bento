#!/usr/bin/env python3
"""SessionStart hook: writes session_id to ~/.claude/session_id and creates
a per-session scratch directory at /tmp/claude-session-<id>/."""

import json
import os
import sys
from pathlib import Path


def run(hook_input: dict, home: Path | None = None, tmp: Path | None = None) -> None:
    session_id = hook_input.get("session_id", "")
    if not session_id:
        return

    base = home or Path.home()
    (base / ".claude").mkdir(exist_ok=True)
    (base / ".claude" / "session_id").write_text(session_id + "\n", encoding="utf-8")

    scratch_root = tmp or Path("/tmp")
    (scratch_root / f"claude-session-{session_id}").mkdir(exist_ok=True)


def main() -> None:
    hook_input = json.load(sys.stdin)
    run(hook_input)


if __name__ == "__main__":
    main()
