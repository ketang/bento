#!/usr/bin/env python3
"""Internal CLI for inspecting local bento telemetry."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import bento_telemetry  # noqa: E402


ZERO_SUMMARY = {
    "total": 0,
    "by_class": {},
    "by_plugin": {},
    "by_skill": {},
    "by_day": {},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("path", help="print the telemetry store path")

    tail_parser = subparsers.add_parser("tail", help="print telemetry records")
    _add_filter_args(tail_parser)
    tail_parser.add_argument("--json", action="store_true", help="emit JSON")
    tail_parser.add_argument("-n", "--limit", type=int, default=None)

    summarize_parser = subparsers.add_parser("summarize", help="summarize telemetry records")
    _add_filter_args(summarize_parser)
    summarize_parser.add_argument("--json", action="store_true", help="emit JSON")

    subparsers.add_parser("export", help="reserved for future telemetry export")

    args = parser.parse_args(argv)
    if args.command == "path":
        print(bento_telemetry.store_dir())
        return 0
    if args.command == "tail":
        return cmd_tail(args)
    if args.command == "summarize":
        return cmd_summarize(args)
    if args.command == "export":
        print("telemetry export is not implemented", file=sys.stderr)
        return 2
    return 2


def cmd_tail(args: argparse.Namespace) -> int:
    records = apply_filters(read_records(), args)
    if args.limit is not None:
        records = records[-max(args.limit, 0) :]
    if args.json:
        print(stable_json(records))
    else:
        for record in records:
            print(format_record(record))
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    records = apply_filters(read_records(), args)
    summary = summarize(records)
    if args.json:
        print(stable_json(summary))
    else:
        print(f"total {summary['total']}")
        for key, value in summary["by_class"].items():
            print(f"class {key} {value}")
    return 0


def read_records() -> list[dict[str, Any]]:
    store = bento_telemetry.store_dir()
    records: list[dict[str, Any]] = []
    for path in sorted(store.glob("*.jsonl")):
        for line in _read_lines(path):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
    return sorted(records, key=record_sort_key)


def apply_filters(records: Iterable[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    since = parse_timestamp(args.since) if getattr(args, "since", None) else None
    filtered: list[dict[str, Any]] = []
    for record in records:
        if since is not None:
            ts = parse_timestamp(str(record.get("ts", "")))
            if ts is None or ts < since:
                continue
        if args.skill and record.get("skill") != args.skill:
            continue
        if args.plugin and record.get("plugin") != args.plugin:
            continue
        if args.event_class and record.get("class") != args.event_class:
            continue
        if args.session and record.get("session_id") != args.session:
            continue
        filtered.append(record)
    return filtered


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return dict(ZERO_SUMMARY)
    by_class: Counter[str] = Counter()
    by_plugin: Counter[str] = Counter()
    by_skill: Counter[str] = Counter()
    by_day: Counter[str] = Counter()
    for record in records:
        by_class[str(record.get("class", ""))] += 1
        by_plugin[str(record.get("plugin", ""))] += 1
        by_skill[str(record.get("skill", ""))] += 1
        ts = parse_timestamp(str(record.get("ts", "")))
        day = ts.astimezone(timezone.utc).strftime("%Y-%m-%d") if ts else ""
        by_day[day] += 1
    return {
        "total": len(records),
        "by_class": ordered_counter(by_class),
        "by_plugin": ordered_counter(by_plugin),
        "by_skill": ordered_counter(by_skill),
        "by_day": ordered_counter(by_day),
    }


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def record_sort_key(record: dict[str, Any]) -> tuple[str, str]:
    ts = parse_timestamp(str(record.get("ts", "")))
    sortable_ts = ts.isoformat(timespec="microseconds") if ts else ""
    return sortable_ts, str(record.get("id", ""))


def ordered_counter(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def format_record(record: dict[str, Any]) -> str:
    return " ".join(
        [
            str(record.get("ts", "")),
            str(record.get("class", "")),
            str(record.get("plugin", "")),
            str(record.get("skill", "")),
            str(record.get("script", "")),
        ]
    ).strip()


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since", help="include records at or after this timestamp")
    parser.add_argument("--skill")
    parser.add_argument("--plugin")
    parser.add_argument("--class", dest="event_class")
    parser.add_argument("--session")


if __name__ == "__main__":
    raise SystemExit(main())
