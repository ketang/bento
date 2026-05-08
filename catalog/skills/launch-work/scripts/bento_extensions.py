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
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


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


HUMAN_HANDOFF_EXIT = 75


@dataclass
class HookContext:
    repo_root: Path
    skill: str
    position: str
    branch: str = ""
    worktree: str = ""
    base_ref: str = ""
    base_sha: str = ""
    head_sha: str = ""
    merge_sha: str = ""
    landed: str = ""
    runtime: str = "unknown"
    task_id: str = ""
    timeout: str = ""


def build_hook_env(ctx: HookContext, parent_env: dict[str, str]) -> dict[str, str]:
    env = dict(parent_env)
    env["BENTO_HOOK_PHASE"] = ctx.skill
    env["BENTO_HOOK_POSITION"] = ctx.position
    env["BENTO_HOOK_REPO_ROOT"] = str(ctx.repo_root)
    env["BENTO_HOOK_WORKTREE"] = ctx.worktree
    env["BENTO_HOOK_BRANCH"] = ctx.branch
    env["BENTO_HOOK_BASE_REF"] = ctx.base_ref
    env["BENTO_HOOK_BASE_SHA"] = ctx.base_sha
    env["BENTO_HOOK_HEAD_SHA"] = ctx.head_sha
    env["BENTO_HOOK_MERGE_SHA"] = ctx.merge_sha
    env["BENTO_HOOK_LANDED"] = ctx.landed
    env["BENTO_HOOK_RUNTIME"] = ctx.runtime
    env["BENTO_HOOK_TASK_ID"] = ctx.task_id
    env["BENTO_HOOK_TTY"] = "1" if sys.stdin.isatty() else "0"
    env["BENTO_HOOK_TIMEOUT"] = ctx.timeout
    env["BENTO_HOOK_REQUIRES_HUMAN"] = str(HUMAN_HANDOFF_EXIT)
    return env


@dataclass
class HookOutcome:
    path: Path
    returncode: int
    timed_out: bool = False


def run_hooks(
    hooks: list[Path],
    ctx: HookContext,
    advisory: bool,
    cwd: Path,
    parent_env: dict[str, str],
) -> tuple[int, list[HookOutcome]]:
    """Run hooks in order. Returns (overall_exit, per-hook outcomes).

    overall_exit is:
      0 if all passed (or advisory mode);
      75 if any hook returned 75 (non-advisory);
      other non-zero if any hook failed (non-advisory).

    In advisory mode the loop continues past failures; the caller is expected
    to surface the messages without halting.
    """
    env = build_hook_env(ctx, parent_env)
    outcomes: list[HookOutcome] = []

    timeout_seconds: Optional[float] = None
    if ctx.timeout:
        try:
            timeout_seconds = float(ctx.timeout)
        except ValueError:
            timeout_seconds = None

    overall = 0
    for hook in hooks:
        try:
            proc = subprocess.run(
                [str(hook)],
                cwd=str(cwd),
                env=env,
                timeout=timeout_seconds,
                check=False,
            )
            outcome = HookOutcome(path=hook, returncode=proc.returncode)
        except subprocess.TimeoutExpired:
            outcome = HookOutcome(path=hook, returncode=124, timed_out=True)

        outcomes.append(outcome)

        if outcome.returncode != 0 and not advisory:
            overall = outcome.returncode
            break

    return overall, outcomes
