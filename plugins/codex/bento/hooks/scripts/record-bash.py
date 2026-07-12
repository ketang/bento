#!/usr/bin/env python3
"""Codex PostToolUse(Bash) hook for bento helper telemetry."""

from __future__ import annotations

import json
import os
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import bento_telemetry  # noqa: E402


class ParsedCommand(NamedTuple):
    argv: list[str]
    realpath: str


class BashEvent(NamedTuple):
    command: str
    cwd: str
    exit_code: int
    stderr: str
    interrupted: bool
    duration_ms: int | None
    session_id: str | None


INTERPRETERS = {"python", "python3", "bash", "sh"}


def parse_bash_command(command: str, cwd: str | None = None) -> ParsedCommand | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None

    tokens = _strip_assignments(tokens)
    if tokens and Path(tokens[0]).name == "rtk":
        tokens = _strip_assignments(tokens[1:])
    if tokens and Path(tokens[0]).name == "env":
        tokens = _strip_env_wrapper(tokens[1:])
    if tokens and Path(tokens[0]).name in INTERPRETERS:
        tokens = tokens[1:]
    if not tokens:
        return None

    script = tokens[0]
    realpath = _realpath(script, cwd=cwd)
    if bento_telemetry.attribute(realpath) is None:
        return None
    return ParsedCommand(argv=[script, *tokens[1:]], realpath=realpath)


def event_from_payload(payload: dict[str, Any]) -> BashEvent:
    tool_input = _mapping(payload.get("tool_input") or payload.get("input"))
    tool_response = _mapping(
        payload.get("tool_response")
        or payload.get("tool_output")
        or payload.get("response")
        or payload.get("output")
    )
    command = _string(tool_input.get("command") or payload.get("command"))
    # hook-cwd-exempt: payload cwd/working_directory are the primary sources;
    # os.getcwd() is only a last-resort fallback when neither is present.
    cwd = _string(tool_input.get("cwd") or tool_input.get("working_directory") or os.getcwd())
    return BashEvent(
        command=command,
        cwd=cwd,
        exit_code=_int_value(
            tool_response.get("exit_code")
            or tool_response.get("exitCode")
            or tool_response.get("status")
            or payload.get("exit_code"),
            default=0,
        ),
        stderr=_string(
            tool_response.get("stderr")
            or tool_response.get("error")
            or payload.get("stderr")
        ),
        interrupted=_bool_value(
            tool_response.get("interrupted")
            or payload.get("interrupted")
            or tool_response.get("timed_out")
        ),
        duration_ms=_optional_int(
            tool_response.get("duration_ms")
            or tool_response.get("durationMs")
            or payload.get("duration_ms")
        ),
        session_id=_optional_string(payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID")),
    )


def main() -> int:
    try:
        payload = _read_payload()
        if payload is None:
            return 0
        event = event_from_payload(payload)
        parsed = parse_bash_command(event.command, cwd=event.cwd)
        if parsed is None:
            return 0
        record = bento_telemetry.make_script_record(
            argv=parsed.argv,
            exit_code=event.exit_code,
            stderr=event.stderr,
            interrupted=event.interrupted,
            duration_ms=event.duration_ms,
            realpath=parsed.realpath,
            session_id=event.session_id,
            now=_now(),
        )
        if record is None:
            return 0
        if os.environ.get("BENTO_TELEMETRY_FORCE_APPEND_ERROR") == "1":
            raise RuntimeError("forced append error")
        bento_telemetry.append_record(record, now=_now())
    except Exception as exc:  # Hooks must never block tool use.
        _log_internal_error(exc)
    return 0


def _read_payload() -> dict[str, Any] | None:
    raw = sys.stdin.read()
    if raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    payload: dict[str, Any] = {}
    tool_input = _json_env("CLAUDE_TOOL_INPUT")
    tool_output = _json_env("CLAUDE_TOOL_OUTPUT")
    if tool_input is not None:
        payload["tool_input"] = tool_input
    if tool_output is not None:
        payload["tool_response"] = tool_output
    if os.environ.get("CLAUDE_SESSION_ID"):
        payload["session_id"] = os.environ["CLAUDE_SESSION_ID"]
    return payload or None


def _json_env(name: str) -> Any | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _log_internal_error(exc: Exception) -> None:
    try:
        path = bento_telemetry.store_dir() / "hook-errors.log"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{_format_now()} {type(exc).__name__}: {exc}\n")
    except Exception:
        pass


def _now() -> datetime | None:
    raw = os.environ.get("BENTO_TELEMETRY_NOW")
    if not raw:
        return None
    value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_now() -> str:
    now = _now() or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _realpath(path: str, cwd: str | None = None) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        # hook-cwd-exempt: resolves a relative path against the caller-provided
        # cwd (sourced from the payload); os.getcwd() is only the fallback.
        candidate = Path(cwd or os.getcwd()) / candidate
    return str(candidate.resolve(strict=False))


def _strip_assignments(tokens: list[str]) -> list[str]:
    while tokens and _is_assignment(tokens[0]):
        tokens = tokens[1:]
    return tokens


def _strip_env_wrapper(tokens: list[str]) -> list[str]:
    while tokens and (_is_assignment(tokens[0]) or tokens[0].startswith("-")):
        tokens = tokens[1:]
    return tokens


def _is_assignment(token: str) -> bool:
    if "=" not in token:
        return False
    name = token.split("=", 1)[0]
    return bool(name) and not name[0].isdigit() and name.replace("_", "").isalnum()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_value(value: Any, *, default: int) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


if __name__ == "__main__":
    raise SystemExit(main())
