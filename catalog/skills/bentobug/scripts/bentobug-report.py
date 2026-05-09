#!/usr/bin/env python3
"""bentobug report writer.

Captures a structured bento bug report as one JSON file per report under
$BENTO_BENTOBUG_DIR (or $XDG_STATE_HOME/bento/bentobug). Telemetry enrichment
is best-effort and optional: reporting proceeds when telemetry is absent,
disabled, empty, or corrupt.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SCHEMA_VERSION = 1
RECORD_KIND = "bentobug_report"
SLUG_MAX_LEN = 50


def ulid() -> str:
    ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    n = (ts_ms << 80) | rand
    out = []
    for _ in range(26):
        out.append(CROCKFORD[n & 0x1F])
        n >>= 5
    return "".join(reversed(out))


def slugify(text: str, max_len: int = SLUG_MAX_LEN) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s


def store_dir() -> Path:
    override = os.environ.get("BENTO_BENTOBUG_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(xdg) / "bento" / "bentobug"


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(msg, file=sys.stderr)
    sys.exit(2)


def build_filename(record_id: str, target: str, note: str) -> str:
    target_part = slugify(target) or "unknown"
    note_part = slugify(note)
    if note_part:
        return f"{record_id}-{target_part}-{note_part}.json"
    return f"{record_id}-{target_part}.json"


def _telemetry_store_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "bento" / "telemetry"


def read_telemetry_context(target: str, telemetry_dir: Path) -> "dict[str, object] | None":
    """Return the most recent telemetry record for *target*, or None on any failure."""
    try:
        if not telemetry_dir.is_dir():
            return None
        best: "dict[str, object] | None" = None
        best_ts: str = ""
        for jsonl_path in sorted(telemetry_dir.glob("*.jsonl"), reverse=True):
            try:
                text = jsonl_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or rec.get("skill") != target:
                    continue
                ts = str(rec.get("ts") or "")
                if not best or ts > best_ts:
                    best = rec
                    best_ts = ts
        if not best:
            return None
        ctx: dict[str, object] = {"ts": best_ts}
        for field in ("skill", "script", "exit", "class", "duration_ms"):
            if field in best:
                ctx[field] = best[field]
        return ctx
    except Exception:
        return None


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="bentobug-report")
    p.add_argument("--note", required=True, help="bug description (non-empty)")
    p.add_argument("--target", help="bento component the bug is about")
    p.add_argument(
        "--target-resolution",
        choices=("explicit", "inferred"),
        default="explicit",
    )
    p.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="candidate component(s) considered (repeatable)",
    )
    p.add_argument("--cwd")
    p.add_argument("--branch")
    p.add_argument("--worktree")
    p.add_argument("--context")
    p.add_argument(
        "--telemetry-dir",
        help="override telemetry directory for enrichment (default: XDG_STATE_HOME/bento/telemetry)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    note = args.note.strip()
    if not note:
        fail("note is empty or whitespace-only")

    target = (args.target or "").strip()
    candidates = [c for c in (args.candidate or []) if c]
    if not target:
        if len(candidates) >= 2:
            fail(f"ambiguous target: candidates were {candidates}")
        fail("missing target")

    record_id = ulid()
    record: dict[str, object] = {
        "v": SCHEMA_VERSION,
        "kind": RECORD_KIND,
        "id": record_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "target_resolution": args.target_resolution,
        "note": note,
    }
    if candidates:
        record["candidates"] = candidates
    for field in ("branch", "worktree", "cwd", "context"):
        value = getattr(args, field, None)
        if value:
            record[field] = value

    telemetry_dir = Path(args.telemetry_dir) if args.telemetry_dir else _telemetry_store_dir()
    ctx = read_telemetry_context(target, telemetry_dir)
    if ctx is not None:
        record["telemetry_context"] = ctx

    base = store_dir()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(base, 0o700)

    filename = build_filename(record_id, target, note)
    target_path = base / filename
    tmp_path = base / f".tmp-{record_id}.json"

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, target_path)

    print(json.dumps({"id": record_id, "path": str(target_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
