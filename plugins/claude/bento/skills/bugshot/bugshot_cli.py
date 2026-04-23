#!/usr/bin/env python3

"""Command-line entrypoint for standalone bugshot review sessions."""

from __future__ import annotations

import argparse
import os

from bugshot_workflow import (
    DEFAULT_BIND_ADDRESS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    LOOPBACK_BIND_ADDRESS,
    ShellIO,
    run_review_session,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bugshot standalone CLI")
    parser.add_argument("directory", help="Path to screenshot directory")
    bind_group = parser.add_mutually_exclusive_group()
    bind_group.add_argument(
        "--bind",
        default=DEFAULT_BIND_ADDRESS,
        help=f"Address to bind to (default: {DEFAULT_BIND_ADDRESS}, all interfaces)",
    )
    bind_group.add_argument(
        "--local-only",
        action="store_true",
        help=f"Shortcut for --bind {LOOPBACK_BIND_ADDRESS} (loopback only)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Polling interval in seconds for review completion",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the gallery URL in the default browser",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout instead of markdown text",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    io = ShellIO(json_output=args.json)

    if not os.path.isdir(args.directory):
        io.write_error(f"Not a directory: {args.directory}")
        return 2

    bind_address = LOOPBACK_BIND_ADDRESS if args.local_only else args.bind

    try:
        return run_review_session(
            screenshot_dir=os.path.abspath(args.directory),
            io=io,
            bind_address=bind_address,
            open_browser=args.open_browser,
            poll_interval_seconds=args.poll_interval,
            json_output=args.json,
        )
    except Exception as error:  # pragma: no cover - top-level CLI handling
        io.write_error(f"Bugshot CLI failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
