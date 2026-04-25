#!/usr/bin/env python3
"""Bento /handoff helper.

Writes a markdown handoff prompt to /tmp/ on success. Refuses to write when
preconditions fail (not in a git repo, detached HEAD, or active expedition).
See catalog/skills/handoff/SKILL.md for the runtime contract."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _is_inside_work_tree(cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _has_named_branch(cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "HEAD"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _expedition_script_path() -> Path:
    override = os.environ.get("BENTO_EXPEDITION_SCRIPT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "expedition" / "scripts" / "expedition.py"


def _active_expedition(cwd: Path) -> str | None:
    script = _expedition_script_path()
    if not script.exists():
        return None
    result = subprocess.run(
        [str(script), "discover"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for entry in payload.get("expeditions", []):
        if entry.get("current_checkout"):
            return str(entry.get("expedition") or "")
    return None


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
    cwd = Path.cwd().resolve()
    if not _is_inside_work_tree(cwd):
        print(
            "/handoff: not in a git repository; refusing to write a handoff file.",
            file=sys.stderr,
        )
        return 2
    if not _has_named_branch(cwd):
        print(
            "/handoff: HEAD is detached; refusing to write a handoff file. "
            "Check out a named branch.",
            file=sys.stderr,
        )
        return 2
    expedition_name = _active_expedition(cwd)
    if expedition_name:
        print(
            f"/handoff: active expedition {expedition_name} detected; "
            f"use the expedition skill's session-end protocol instead "
            f"(update docs/expeditions/{expedition_name}/handoff.md via "
            f"expedition/scripts/expedition.py).",
            file=sys.stderr,
        )
        return 2
    del args
    return 0


if __name__ == "__main__":
    sys.exit(main())
