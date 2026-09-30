"""Client-side parsing, Unix-socket transport, and result presentation."""

from __future__ import annotations

import argparse
import array
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile
from typing import Any

from . import CONTRACT_VERSION, IMPLEMENTATION_VERSION

SOCKET_PATH = "/run/bento-governor/v1.sock"
RESULT_PREFIX = "BENTO_GOVERNOR_RESULT "
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class UsageError(Exception):
    """The caller supplied an invalid invocation."""


class GovernorParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def parser() -> GovernorParser:
    top = GovernorParser(prog="bento-governor-v1")
    top.add_argument("--version", action="store_true")
    commands = top.add_subparsers(dest="action", parser_class=GovernorParser)

    run = commands.add_parser("run")
    selection = run.add_mutually_exclusive_group()
    selection.add_argument("--weight", type=int, default=1)
    selection.add_argument("--exclusive", action="store_true")
    run.add_argument("--max-wait", type=float)
    run.add_argument("--result-file", type=Path)
    run.add_argument("--repo", required=True)
    run.add_argument("--label", required=True)
    run.add_argument("--bypass", choices=("admission", "uncontained"))
    run.add_argument("--reason")
    run.add_argument("command", nargs=argparse.REMAINDER)

    signals = commands.add_parser("signals")
    signals.add_argument("--json", action="store_true", required=True)
    signal_selection = signals.add_mutually_exclusive_group()
    signal_selection.add_argument("--weight", type=int, default=1)
    signal_selection.add_argument("--exclusive", action="store_true")
    signals.add_argument("--cwd", type=Path, default=Path.cwd())

    events = commands.add_parser("events")
    events.add_argument("--jsonl", action="store_true", required=True)
    events.add_argument("--since")

    serve = commands.add_parser("serve")
    serve.add_argument("--config", type=Path, default=Path("/etc/bento-governor/v1.toml"))
    return top


def _validate(args: argparse.Namespace) -> None:
    if args.action == "run":
        if args.weight < 1 or args.max_wait is not None and args.max_wait < 0:
            raise UsageError("weight must be positive and max-wait must be nonnegative")
        if not args.command or args.command[0] != "--" or len(args.command) < 2:
            raise UsageError("run requires -- CMD [ARG...]")
        args.command = args.command[1:]
        if args.bypass and (not args.reason or not args.reason.strip()):
            raise UsageError("bypass requires a nonempty --reason")
        if args.reason and not args.bypass:
            raise UsageError("--reason requires --bypass")
        if not args.repo.strip() or not args.label.strip():
            raise UsageError("repo and label must be nonempty")
    elif args.action == "signals":
        if args.weight < 1:
            raise UsageError("weight must be positive")
    elif args.action is None and not args.version:
        raise UsageError("a command is required")


def _result(outcome: str, *, lease_id: str | None = None, wait_seconds: float = 0.0,
            child_exit_code: int | None = None, detail: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": CONTRACT_VERSION,
        "outcome": outcome,
        "lease_id": lease_id,
        "wait_seconds": wait_seconds,
        "child_exit_code": child_exit_code,
        **({"detail": detail} if detail else {}),
    }


def _print_result(result: dict[str, Any]) -> None:
    print(RESULT_PREFIX + json.dumps(result, separators=(",", ":"), sort_keys=True), file=sys.stderr)


def _check_result_destination(path: Path) -> None:
    parent = path.expanduser().absolute().parent
    descriptor, temporary = tempfile.mkstemp(prefix=".governor-check-", dir=parent)
    os.close(descriptor)
    os.unlink(temporary)


def _write_result(path: Path, result: dict[str, Any]) -> None:
    destination = path.expanduser().absolute()
    descriptor, temporary = tempfile.mkstemp(prefix=".governor-result-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(result, output, separators=(",", ":"), sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _request(message: dict[str, Any], *, forward_stdio: bool = False) -> dict[str, Any]:
    payload = json.dumps(message, separators=(",", ":")).encode() + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(SOCKET_PATH)
        if forward_stdio:
            descriptors = array.array("i", (0, 1, 2))
            connection.sendmsg([payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptors)])
        else:
            connection.sendall(payload)
        previous = {}
        if forward_stdio:  # forward SIGINT/SIGTERM to the scope; the service keeps the lease until it empties
            def forward(signum, _frame):
                try:
                    connection.send(b"TERM\n" if signum == signal.SIGTERM else b"INT\n")
                except OSError:
                    pass
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, forward)
        try:
            return _read_response(connection)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)


def _read_response(connection: socket.socket) -> dict[str, Any]:
    response = bytearray()
    while b"\n" not in response:
        chunk = connection.recv(65536)
        if not chunk:
            raise OSError("governor service disconnected without a result")
        response.extend(chunk)
        if len(response) > MAX_RESPONSE_BYTES:
            raise OSError("governor response exceeded size limit")
    value = json.loads(response.split(b"\n", 1)[0])
    if not isinstance(value, dict) or value.get("schema_version") != CONTRACT_VERSION:
        raise OSError("incompatible governor response")
    return value


def _run(args: argparse.Namespace) -> int:
    if args.result_file:
        try:
            _check_result_destination(args.result_file)
        except OSError as error:
            result = _result("infra-error", detail=str(error))
            _print_result(result)
            return 70
    message = {
        "schema_version": CONTRACT_VERSION,
        "action": "run",
        "repo": args.repo,
        "label": args.label,
        "weight": args.weight,
        "exclusive": args.exclusive,
        "max_wait": args.max_wait,
        "bypass": args.bypass,
        "reason": args.reason,
        "command": args.command,
        "cwd": os.getcwd(),
        "environment": dict(os.environ),
        "has_tty": sys.stdin.isatty(),
        "tty": os.ttyname(0) if sys.stdin.isatty() else None,
    }
    try:
        response = _request(message, forward_stdio=True)
    except (OSError, ValueError) as error:
        response = {"schema_version": CONTRACT_VERSION, "exit_code": 70,
                    "result": _result("infra-error", detail=str(error))}
    result = response.get("result", _result("infra-error", detail="missing result"))
    exit_code = response.get("exit_code", 70)
    if args.result_file:
        try:
            _write_result(args.result_file, result)
        except OSError as error:
            result = _result("infra-error", lease_id=result.get("lease_id"),
                             wait_seconds=result.get("wait_seconds", 0.0),
                             child_exit_code=result.get("child_exit_code"), detail=str(error))
            exit_code = 70
    _print_result(result)
    return exit_code if isinstance(exit_code, int) and 0 <= exit_code <= 255 else 70


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        _validate(args)
    except UsageError as error:
        print(f"bento-governor-v1: {error}", file=sys.stderr)
        _print_result(_result("invalid-args", detail=str(error)))
        return 64
    if args.version:
        print(f"bento-governor-v1 contract={CONTRACT_VERSION} implementation={IMPLEMENTATION_VERSION} source=dev")
        return 0
    if args.action == "run":
        return _run(args)
    if args.action == "serve":
        from .server import serve
        return serve(args.config)
    try:
        response = _request({
            "schema_version": CONTRACT_VERSION,
            "action": args.action,
            "weight": getattr(args, "weight", 1),
            "exclusive": getattr(args, "exclusive", False),
            "cwd": str(getattr(args, "cwd", Path.cwd())),
            "environment": dict(os.environ),
            "since": getattr(args, "since", None),
        })
    except (OSError, ValueError) as error:
        print(f"bento-governor-v1: {error}", file=sys.stderr)
        return 70
    if args.action == "signals":
        print(json.dumps(response.get("signals", {}), separators=(",", ":")))
        return 70 if response.get("signals", {}).get("status") == "error" else 0
    for event in response.get("events", []):
        print(json.dumps(event, separators=(",", ":")))
    return response.get("exit_code", 70)


if __name__ == "__main__":
    raise SystemExit(main())
