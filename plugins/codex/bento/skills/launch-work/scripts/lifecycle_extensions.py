"""Discover and run launch-work / land-work project extensions.

This module is the importable core. The CLI front end is run-lifecycle-extensions.py
in the same directory.

Layout under `<root>/.agent-plugins/bento/bento/`:

    <skill>/<kind>/<position>/<two-digit>-<slug>.<ext>

where <skill> is launch-work or land-work, <kind> is hook-scripts or hook-skills,
<position> is pre or post. <ext> is shell-executable for hook-scripts, .md for
hook-skills.
"""

from __future__ import annotations

import json
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import agent_plugins_resolver


PREFIX_RE = re.compile(r"^(\d{2})-(.+)$")
BACKUP_SUFFIXES = ("~", ".bak", ".swp", ".orig")


@dataclass
class DiscoveryResult:
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def discover_directory(directory: Path, kind: str) -> DiscoveryResult:
    """Return ordered, filtered files from one position directory.

    kind is "hook-scripts" or "hook-skills".
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

        if kind == "hook-scripts":
            mode = entry.stat().st_mode
            is_executable = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            if not is_executable:
                continue
        elif kind == "hook-skills":
            if entry.suffix != ".md":
                continue
        else:
            raise ValueError(f"unknown kind: {kind!r}")

        candidates.append((int(match.group(1)), name, entry))

    candidates.sort(key=lambda t: (t[0], t[1]))
    result.files = [p for _, _, p in candidates]
    return result


def _candidate_roots(repo_root: Path) -> list[Path]:
    """Return the ordered agent-plugins roots: repo scope, then home scope."""
    return [
        (repo_root / ".agent-plugins/bento/bento").resolve(),
        agent_plugins_resolver.home_scope_base() / "bento" / "bento",
    ]


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
    if kind not in ("hook-scripts", "hook-skills"):
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


# --------------------------------------------------------------------------- #
# Project verifier manifest discovery (land-work)
# --------------------------------------------------------------------------- #

VERIFIER_MANIFEST_NAME = "verifier.json"
VERIFIER_SCHEMA_VERSION = 1


@dataclass
class VerifierManifest:
    manifest_path: Path
    command: list[str]
    verified_noop: list[dict] = field(default_factory=list)


@dataclass
class VerifierDiscovery:
    """Result of locating the land-work verifier manifest.

    `manifest` is populated only when a manifest exists AND passes shape
    validation. `manifest_path` records the first existing manifest (even if it
    later fails validation). `searched_paths` is the ordered candidate list, so
    a caller with no manifest can report the exact config path to create.
    `errors` holds shape/parse problems; an absent manifest is NOT an error
    here — the caller decides whether absence is fatal for a given diff.
    """

    manifest: Optional[VerifierManifest] = None
    manifest_path: Optional[Path] = None
    searched_paths: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def verifier_manifest_paths(repo_root: Path) -> list[Path]:
    """Ordered candidate manifest paths, repo-local first then the XDG root."""
    return [
        root / "land-work" / VERIFIER_MANIFEST_NAME
        for root in _candidate_roots(repo_root)
    ]


def _validate_verifier_shape(raw: object, manifest_path: Path) -> list[str]:
    """Structural (candidate-independent) validation of a parsed manifest.

    Path-relative checks (absolute/.., globs, existence, dedup) depend on the
    candidate worktree and live in the land-work-run-verifier helper.
    """
    errors: list[str] = []
    if not isinstance(raw, dict):
        return [f"verifier manifest must be a JSON object: {manifest_path}"]

    if raw.get("schema_version") != VERIFIER_SCHEMA_VERSION:
        errors.append(
            f"verifier manifest schema_version must be {VERIFIER_SCHEMA_VERSION}: "
            f"{manifest_path}"
        )

    command = raw.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
    ):
        errors.append(
            f"verifier manifest command must be a nonempty argv array of "
            f"nonempty strings: {manifest_path}"
        )

    verified_noop = raw.get("verified_noop", [])
    if not isinstance(verified_noop, list):
        errors.append(
            f"verifier manifest verified_noop must be a list: {manifest_path}"
        )
    else:
        for index, entry in enumerate(verified_noop):
            if not isinstance(entry, dict):
                errors.append(
                    f"verified_noop[{index}] must be an object: {manifest_path}"
                )
                continue
            path_value = entry.get("path")
            reason_value = entry.get("reason")
            if not isinstance(path_value, str) or not path_value:
                errors.append(
                    f"verified_noop[{index}].path must be a nonempty string: "
                    f"{manifest_path}"
                )
            if not isinstance(reason_value, str) or not reason_value:
                errors.append(
                    f"verified_noop[{index}].reason must be a nonempty string: "
                    f"{manifest_path}"
                )
    return errors


def discover_verifier(repo_root: Path) -> VerifierDiscovery:
    """Locate the land-work verifier manifest across the candidate-root chain.

    The first existing manifest wins as a whole — repo-local overrides the XDG
    root. Commands and exemptions are never merged across roots.
    """
    searched = verifier_manifest_paths(repo_root)
    discovery = VerifierDiscovery(searched_paths=searched)

    chosen: Optional[Path] = None
    for candidate in searched:
        if candidate.is_file():
            chosen = candidate
            break
    if chosen is None:
        return discovery

    discovery.manifest_path = chosen
    try:
        raw = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        discovery.errors.append(
            f"verifier manifest is not valid JSON: {chosen}: {exc}"
        )
        return discovery

    shape_errors = _validate_verifier_shape(raw, chosen)
    if shape_errors:
        discovery.errors.extend(shape_errors)
        return discovery

    discovery.manifest = VerifierManifest(
        manifest_path=chosen,
        command=list(raw["command"]),
        verified_noop=[
            {"path": entry["path"], "reason": entry["reason"]}
            for entry in raw.get("verified_noop", [])
        ],
    )
    return discovery


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
