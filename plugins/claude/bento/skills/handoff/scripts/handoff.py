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
from datetime import datetime
from pathlib import Path
from typing import Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import git_state  # noqa: E402
from _agent_plugins_bootstrap import ensure_agent_plugins_resolver_importable  # noqa: E402

ensure_agent_plugins_resolver_importable()
import agent_plugins_resolver  # noqa: E402


MARKETPLACE = "bento"
PLUGIN_NAME = "bento"
TEMPLATE_REL = Path("handoff") / "template.md"


class HandoffError(Exception):
    """Raised when the helper cannot proceed."""


_SUFFIX_VALID = re.compile(r"[A-Za-z0-9._-]")


def sanitize_suffix(branch: str) -> str:
    return "".join(ch if _SUFFIX_VALID.match(ch) else "-" for ch in branch)


def derive_suffix(*, current: str, primary: str, slug: str | None) -> str:
    if slug:
        return sanitize_suffix(slug)
    if current != primary:
        return sanitize_suffix(current)
    raise HandoffError(
        "current branch is the primary branch; pass --slug with a 2-4 word "
        "kebab-case summary so the output filename is meaningful."
    )


def resolve_template(
    *,
    repo_root: Path | None,
    env: Mapping[str, str] | None = None,
    bundled: Path,
    home: Path | None = None,
) -> Path:
    candidate = agent_plugins_resolver.resolve_customization_file(
        marketplace=MARKETPLACE,
        plugin=PLUGIN_NAME,
        rel_path=TEMPLATE_REL,
        repo_root=repo_root,
        bundled_default_path=bundled,
        env=env,
        home=home,
    )
    if candidate is not None:
        return candidate.path
    candidates = agent_plugins_resolver.candidate_paths(
        marketplace=MARKETPLACE,
        plugin=PLUGIN_NAME,
        rel_path=TEMPLATE_REL,
        repo_root=repo_root,
        bundled_default_path=bundled,
        env=env,
        home=home,
    )
    raise HandoffError(
        f"no template found at any candidate path: {[c.path for c in candidates]}"
    )


def _home_scope_target(*, env: Mapping[str, str] | None, home: Path | None) -> Path:
    return (
        agent_plugins_resolver.home_scope_base(env=env, home=home)
        / MARKETPLACE
        / PLUGIN_NAME
        / TEMPLATE_REL
    )


def self_heal_home_template(
    *, env: Mapping[str, str] | None = None, bundled: Path, home: Path | None = None
) -> bool:
    target = _home_scope_target(env=env, home=home)
    if target.is_file():
        return False
    if not bundled.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundled, target)
    return True


def output_path(*, suffix: str, now: datetime, tmp_root: Path) -> Path:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    return tmp_root / f"handoff-{suffix}-{stamp}.md"


def _read_input(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    return Path(arg).read_text(encoding="utf-8")


def _bundled_template_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "references"
        / "templates"
        / "handoff.md"
    )


def _tmp_root() -> Path:
    raw = os.environ.get("HANDOFF_TMP_ROOT")
    if raw:
        return Path(raw)
    return Path("/tmp")


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
        help=(
            "descriptive suffix for the output filename (kebab-case, 2-4 words); "
            "required on the primary branch"
        ),
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

    checkout_root = git_state.detect_checkout_root(cwd)
    primary_branch, _warnings = git_state.detect_primary_branch(checkout_root)
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    try:
        suffix = derive_suffix(
            current=current_branch, primary=primary_branch, slug=args.slug
        )
    except HandoffError as exc:
        print(f"/handoff: {exc}", file=sys.stderr)
        return 2

    bundled = _bundled_template_path()
    self_heal_home_template(env=os.environ, bundled=bundled)

    try:
        resolve_template(repo_root=checkout_root, env=os.environ, bundled=bundled)
    except HandoffError as exc:
        print(f"/handoff: {exc}", file=sys.stderr)
        return 2

    body = _read_input(args.input)
    target = output_path(suffix=suffix, now=datetime.now(), tmp_root=_tmp_root())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")

    if args.verbose:
        print(f"/handoff: wrote {target}", file=sys.stderr)
    print(str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
