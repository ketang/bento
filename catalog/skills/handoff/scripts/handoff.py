#!/usr/bin/env python3
"""Bento /handoff helper.

Writes a markdown handoff prompt to /tmp/ on success. Refuses to write when
preconditions fail (not in a git repo, detached HEAD, or active expedition).
See catalog/skills/handoff/SKILL.md for the runtime contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


MARKETPLACE = "bento"
PLUGIN_NAME = "bento"
TEMPLATE_REL = Path("handoff") / "template.md"


class HandoffError(Exception):
    """Raised when the helper cannot proceed."""


_SUFFIX_VALID = re.compile(r"[A-Za-z0-9._-]")


def sanitize_suffix(branch: str) -> str:
    return "".join(ch if _SUFFIX_VALID.match(ch) else "-" for ch in branch)


def derive_suffix(*, current: str, primary: str, slug: str | None) -> str:
    if current != primary:
        return sanitize_suffix(current)
    if not slug:
        raise HandoffError(
            "current branch is the primary branch; pass --slug with a 2-4 word "
            "kebab-case summary so the output filename is meaningful."
        )
    return sanitize_suffix(slug)


def resolve_template(
    *,
    repo_root: Path | None,
    xdg_config_home: Path | None,
    bundled: Path,
    home: Path | None = None,
) -> Path:
    candidates: list[Path] = []
    if repo_root is not None:
        candidates.append(
            repo_root / ".agent-plugins" / MARKETPLACE / PLUGIN_NAME / TEMPLATE_REL
        )
    if xdg_config_home is not None:
        base = xdg_config_home
    else:
        base = (home or Path.home()) / ".config"
    candidates.append(base / "agent-plugins" / MARKETPLACE / PLUGIN_NAME / TEMPLATE_REL)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    if bundled.is_file():
        return bundled
    raise HandoffError(f"no template found at any candidate path: {candidates}")


def self_heal_home_template(
    *, xdg_config_home: Path | None, bundled: Path, home: Path | None = None
) -> bool:
    if xdg_config_home is not None:
        base = xdg_config_home
    else:
        base = (home or Path.home()) / ".config"
    target = base / "agent-plugins" / MARKETPLACE / PLUGIN_NAME / TEMPLATE_REL
    if target.is_file():
        return False
    if not bundled.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundled, target)
    return True


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
