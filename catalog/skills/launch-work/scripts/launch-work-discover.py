#!/usr/bin/env python3
"""Scan linked worktrees for launch-work progress logs.

The log lives at <worktree-git-dir>/launch-work/log.md. A read-only fallback
to <worktree>/.launch-work/log.md handles in-flight branches that pre-date
the move out of the working tree.

Emits a JSON object with a 'logs' list, one entry per worktree containing a
progress log. See catalog/skills/launch-work/SKILL.md for the runtime
contract."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


LOG_REL_PATH = "launch-work/log.md"
LEGACY_LOG_REL_PATH = ".launch-work/log.md"
HEADER_RE = re.compile(
    r"<!--\s*launch-work-log\s*\n"
    r"last-updated:\s*(?P<last_updated>[^\n]+)\n"
    r"checkpoint:\s*(?P<checkpoint>[^\n]+)\n"
    r"-->",
    re.MULTILINE,
)


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _list_worktrees(cwd: Path) -> list[dict[str, str]]:
    raw = _git(cwd, "worktree", "list", "--porcelain").stdout
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            ref = line.split(" ", 1)[1]
            current["branch"] = ref.split("refs/heads/", 1)[-1]
        elif line == "detached":
            current["branch"] = ""
    if current:
        entries.append(current)
    return entries


def _resolve_log_path(worktree: Path) -> Path | None:
    """Return the log path under the worktree's git-dir, falling back to the
    legacy in-tree path. Returns None if neither exists."""
    git_dir_result = _git(worktree, "rev-parse", "--absolute-git-dir", check=False)
    if git_dir_result.returncode == 0:
        primary = Path(git_dir_result.stdout.strip()) / LOG_REL_PATH
        if primary.is_file():
            return primary
    legacy = worktree / LEGACY_LOG_REL_PATH
    if legacy.is_file():
        return legacy
    return None


def _read_log_header(worktree: Path) -> dict[str, str] | None:
    log_path = _resolve_log_path(worktree)
    if log_path is None:
        return None
    body = log_path.read_text(encoding="utf-8", errors="replace")
    match = HEADER_RE.search(body)
    if not match:
        return {"last_updated": "", "checkpoint": ""}
    return {
        "last_updated": match.group("last_updated").strip(),
        "checkpoint": match.group("checkpoint").strip(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="launch-work-discover")
    parser.parse_args(argv)
    cwd = Path.cwd().resolve()
    worktrees = _list_worktrees(cwd)
    logs: list[dict[str, str]] = []
    for entry in worktrees:
        path = Path(entry.get("path", ""))
        header = _read_log_header(path)
        if header is None:
            continue
        logs.append(
            {
                "branch": entry.get("branch", ""),
                "worktree": str(path),
                "checkpoint": header["checkpoint"],
                "last_updated": header["last_updated"],
            }
        )
    print(json.dumps({"logs": logs}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
