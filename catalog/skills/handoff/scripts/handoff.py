#!/usr/bin/env python3
"""Bento /handoff helper.

Writes a markdown handoff prompt to /tmp/ on success. Refuses to write when
preconditions fail (not in a git repo, detached HEAD, or active expedition).
See catalog/skills/handoff/SKILL.md for the runtime contract."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handoff",
        description="Write a structured session-reboot prompt to /tmp/.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="path to a file containing the filled-in template, or '-' for stdin",
    )
    parser.add_argument(
        "--slug",
        help="suffix to use when on the primary branch (kebab-case, 2-4 words)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print extra diagnostics to stderr",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    del args  # placeholder while later steps add behavior
    return 0


if __name__ == "__main__":
    sys.exit(main())
