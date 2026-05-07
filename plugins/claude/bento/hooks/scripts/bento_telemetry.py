"""Bento telemetry primitives for local helper-script observability."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NOT_FOUND_EXIT_CODES = {126, 127}
NOT_FOUND_PATTERNS = (
    "No such file or directory",
    "command not found",
    "Permission denied",
    "not found",
)
STDERR_TAIL_LINES = 20
STDERR_TAIL_BYTES = 4096
STORE_DIR_MODE = 0o750
STORE_FILE_MODE = 0o640

CACHE_LAYOUT_RE = re.compile(
    r"^(?P<marketplace>[^/]+)/(?P<plugin>[^/]+)/(?P<version>[^/]+)/skills/"
    r"(?P<skill>[^/]+)/scripts/(?P<script>[^/]+)$"
)
DEV_LAYOUT_RE = re.compile(
    r"(?:^|/)catalog/skills/(?P<skill>[^/]+)/scripts/(?P<script>[^/]+)$"
)
SCRATCH_PATH_RE = re.compile(r"/tmp/claude-session-[A-Za-z0-9_.-]+/")


def classify(exit_code: int, stderr: str, interrupted: bool) -> str:
    """Return one of ok, not_found, or error for a script invocation."""
    if interrupted:
        return "error"
    if exit_code == 0:
        return "ok"
    if exit_code in NOT_FOUND_EXIT_CODES and any(
        pattern in stderr for pattern in NOT_FOUND_PATTERNS
    ):
        return "not_found"
    return "error"


def redact_stderr(text: str, home: str | None = None) -> list[str]:
    """Return a redacted stderr tail capped by line count and encoded bytes."""
    if not text:
        return []

    redacted = text
    home_dir = home if home is not None else os.path.expanduser("~")
    if home_dir:
        redacted = redacted.replace(home_dir, "~")
    redacted = SCRATCH_PATH_RE.sub("<scratch>/", redacted)

    encoded = redacted.encode("utf-8")
    if len(encoded) > STDERR_TAIL_BYTES:
        redacted = encoded[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")

    return redacted.splitlines()[-STDERR_TAIL_LINES:]


def store_dir() -> Path:
    """Return and create the local bento telemetry directory."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    path = Path(base) / "bento" / "telemetry"
    path.mkdir(parents=True, exist_ok=True)
    _chmod_quietly(path, STORE_DIR_MODE)
    return path


def attribute(realpath: str) -> dict[str, str] | None:
    """Attribute a real path to a bento script in cache or dev layout."""
    parts = realpath.split("/cache/", 1)
    if len(parts) == 2:
        match = CACHE_LAYOUT_RE.match(parts[1])
        if match:
            return {
                "marketplace": match.group("marketplace"),
                "plugin": match.group("plugin"),
                "skill": match.group("skill"),
                "script": match.group("script"),
            }

    match = DEV_LAYOUT_RE.search(realpath)
    if match:
        return {
            "marketplace": "bento",
            "plugin": "(dev)",
            "skill": match.group("skill"),
            "script": match.group("script"),
        }
    return None


def make_script_record(
    *,
    argv: list[str],
    exit_code: int,
    stderr: str,
    interrupted: bool,
    duration_ms: int | None,
    realpath: str,
    session_id: str | None = None,
    home: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Build a script telemetry record, or None for unwatched paths."""
    if not argv:
        return None

    attribution = attribute(realpath)
    if attribution is None:
        return None

    sid = session_id if session_id is not None else _read_session_id()
    return {
        "v": 1,
        "kind": "script",
        "id": str(uuid.uuid4()),
        "ts": _format_ts(now),
        "session_id": sid,
        "marketplace": attribution["marketplace"],
        "plugin": attribution["plugin"],
        "skill": attribution["skill"],
        "script": attribution["script"],
        "argv_redacted": list(argv[1:]),
        "exit": exit_code,
        "class": classify(exit_code, stderr, interrupted),
        "interrupted": bool(interrupted),
        "duration_ms": duration_ms,
        "stderr_tail": redact_stderr(stderr, home=home),
    }


def jsonl_path_for(now: datetime | None = None) -> Path:
    day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(
        "%Y-%m-%d"
    )
    return store_dir() / f"{day}.jsonl"


def append_record(record: dict[str, Any], now: datetime | None = None) -> Path:
    """Append one compact JSON record to the UTC-dated JSONL store."""
    path = jsonl_path_for(now=now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    _chmod_quietly(path, STORE_FILE_MODE)
    return path


def _format_ts(now: datetime | None = None) -> str:
    ts = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (
        ts.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _read_session_id() -> str:
    try:
        return (Path.home() / ".claude" / "session_id").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        return ""


def _chmod_quietly(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass
