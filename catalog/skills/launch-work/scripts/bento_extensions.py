"""Discover and run launch-work / land-work project extensions.

This module is the importable core. The CLI front end is bento-extensions.py
in the same directory.

Layout under `<root>/.agent-plugins/bento/bento/`:

    <skill>/<kind>/<position>/<two-digit>-<slug>.<ext>

where <skill> is launch-work or land-work, <kind> is hooks or actions,
<position> is pre or post. <ext> is shell-executable for hooks, .md for
actions.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PREFIX_RE = re.compile(r"^(\d{2})-(.+)$")
BACKUP_SUFFIXES = ("~", ".bak", ".swp", ".orig")


@dataclass
class DiscoveryResult:
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def discover_directory(directory: Path, kind: str) -> DiscoveryResult:
    """Return ordered, filtered files from one position directory.

    kind is "hooks" or "actions".
    """
    result = DiscoveryResult()
    if not directory.is_dir():
        return result

    candidates: list[tuple[int, str, Path]] = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        name = entry.name
        if name.startswith("."):
            continue
        if name.endswith(BACKUP_SUFFIXES):
            continue
        if "/" in name or "\\" in name:
            continue
        if not entry.is_file():
            continue

        match = PREFIX_RE.match(name)
        if match is None:
            result.warnings.append(
                f"{entry}: filename does not start with two-digit prefix; ignored"
            )
            continue

        if kind == "hooks":
            mode = entry.stat().st_mode
            is_executable = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            if not is_executable:
                continue
        elif kind == "actions":
            if entry.suffix != ".md":
                continue
        else:
            raise ValueError(f"unknown kind: {kind!r}")

        candidates.append((int(match.group(1)), name, entry))

    candidates.sort(key=lambda t: (t[0], t[1]))
    result.files = [p for _, _, p in candidates]
    return result


def _candidate_roots(repo_root: Path) -> list[Path]:
    """Return the ordered XDG chain of agent-plugins roots."""
    roots: list[Path] = []
    repo_root_dir = (repo_root / ".agent-plugins/bento/bento").resolve()
    roots.append(repo_root_dir)

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        roots.append(Path(xdg) / "agent-plugins/bento/bento")
    else:
        roots.append(Path.home() / ".config/agent-plugins/bento/bento")

    return roots


def discover(
    repo_root: Path,
    skill: str,
    kind: str,
    position: str,
) -> DiscoveryResult:
    """Discover extensions for (skill, kind, position) across the XDG chain.

    Files from earlier roots come first; within each root, files are
    sorted by the rules in discover_directory.
    """
    if skill not in ("launch-work", "land-work"):
        raise ValueError(f"unknown skill: {skill!r}")
    if kind not in ("hooks", "actions"):
        raise ValueError(f"unknown kind: {kind!r}")
    if position not in ("pre", "post"):
        raise ValueError(f"unknown position: {position!r}")

    combined = DiscoveryResult()
    for root in _candidate_roots(repo_root):
        sub = root / skill / kind / position
        result = discover_directory(sub, kind=kind)
        combined.files.extend(result.files)
        combined.warnings.extend(result.warnings)
    return combined
