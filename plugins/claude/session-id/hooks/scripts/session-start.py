#!/usr/bin/env python3
"""SessionStart hook: writes session_id to ~/.claude/session_id and creates
a per-session scratch directory at <tmpdir>/claude-session-<id>/.

Scratch directories older than SCRATCH_MAX_AGE_DAYS are pruned on each
SessionStart so they do not accumulate."""

import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Only session ids matching this pattern are interpolated into a filesystem
# path. Anything else is rejected so a hostile or malformed id cannot escape
# the scratch root (e.g. via "../" or absolute paths).
SESSION_ID_RE = re.compile(r"\A[A-Za-z0-9_.-]+\Z")

SCRATCH_PREFIX = "claude-session-"
SCRATCH_MAX_AGE_DAYS = 7


def _prune_stale_scratch(scratch_root: Path, now: float, max_age_days: int) -> None:
    """Remove claude-session-* scratch dirs older than max_age_days."""
    cutoff = now - max_age_days * 86400
    try:
        entries = list(scratch_root.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.startswith(SCRATCH_PREFIX):
            continue
        try:
            # Skip symlinks: rmtree refuses them anyway, and following one
            # would judge staleness by an unrelated target's mtime.
            if entry.is_symlink() or not entry.is_dir():
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def run(
    hook_input: dict,
    home: Path | None = None,
    tmp: Path | None = None,
    now: float | None = None,
    max_age_days: int = SCRATCH_MAX_AGE_DAYS,
) -> None:
    session_id = hook_input.get("session_id", "")
    # Reject empty, disallowed characters, and all-dot ids ("." / ".." /
    # "...") which are special path components rather than real session ids.
    if not session_id or not SESSION_ID_RE.match(session_id) or set(session_id) <= {"."}:
        return

    base = home or Path.home()
    (base / ".claude").mkdir(exist_ok=True)
    (base / ".claude" / "session_id").write_text(session_id + "\n", encoding="utf-8")

    scratch_root = tmp or Path(tempfile.gettempdir())
    _prune_stale_scratch(scratch_root, time.time() if now is None else now, max_age_days)
    (scratch_root / f"{SCRATCH_PREFIX}{session_id}").mkdir(exist_ok=True)


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
        run(hook_input)
    except Exception:
        # Never block session start.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
