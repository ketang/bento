#!/usr/bin/env python3
"""Resolve agent-plugins customization files.

This module implements the lookup behavior specified by
docs/specs/2026-04-24-agent-plugins-convention-design.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path, PureWindowsPath
from typing import Iterable, Mapping, NamedTuple


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
WINDOWS_FORBIDDEN_CHARS = set('<>:"/\\|?*')


class Candidate(NamedTuple):
    source: str
    path: Path


def home_config_root(
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | str | None = None,
) -> Path:
    """Return the platform config root for agent-plugins home scope."""

    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home_path = Path(home) if home is not None else Path.home()

    if platform.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata)
        userprofile = env.get("USERPROFILE")
        if userprofile:
            return Path(userprofile) / "AppData" / "Roaming"
        return home_path / "AppData" / "Roaming"

    xdg_config_home = env.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home)

    if platform == "darwin":
        return home_path / "Library" / "Application Support"

    return home_path / ".config"


def home_scope_base(
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | str | None = None,
) -> Path:
    """Return the home-scope agent-plugins base directory."""

    return home_config_root(env=env, platform=platform, home=home) / "agent-plugins"


def find_repo_root(start: Path | str) -> Path | None:
    """Find the nearest ancestor containing a .git file or directory."""

    current = Path(start).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _validate_identifier_segment(value: str, label: str) -> str:
    if value in {"", ".", ".."}:
        raise ValueError(f"{label} must be a non-empty path segment")
    if any(char in WINDOWS_FORBIDDEN_CHARS for char in value):
        raise ValueError(f"{label} contains a forbidden path character: {value!r}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} contains a control character: {value!r}")
    if value.endswith((" ", ".")):
        raise ValueError(f"{label} is not portable on Windows: {value!r}")

    stem = value.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} uses a reserved Windows device name: {value!r}")

    return value


def _safe_relative_path(rel_path: Path | str) -> Path:
    raw = str(rel_path)
    if raw == "":
        raise ValueError("rel_path must not be empty")

    path = Path(raw)
    windows_path = PureWindowsPath(raw)
    if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError(f"rel_path must be relative: {raw!r}")

    parts = []
    for part in raw.replace("\\", "/").split("/"):
        if part in {"", "."}:
            raise ValueError(
                f"rel_path contains an empty or current-directory segment: {raw!r}"
            )
        if part == "..":
            raise ValueError(f"rel_path must not escape the plugin root: {raw!r}")
        parts.append(_validate_identifier_segment(part, "rel_path segment"))

    return Path(*parts)


def candidate_paths(
    *,
    marketplace: str,
    plugin: str,
    rel_path: Path | str,
    repo_root: Path | str | None = None,
    bundled_default_path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | str | None = None,
) -> list[Candidate]:
    """Return lookup candidates in spec precedence order."""

    marketplace = _validate_identifier_segment(marketplace, "marketplace")
    plugin = _validate_identifier_segment(plugin, "plugin")
    rel = _safe_relative_path(rel_path)

    candidates: list[Candidate] = []
    if repo_root is not None:
        candidates.append(
            Candidate(
                "repo",
                Path(repo_root) / ".agent-plugins" / marketplace / plugin / rel,
            )
        )

    candidates.append(
        Candidate(
            "home",
            home_scope_base(env=env, platform=platform, home=home)
            / marketplace
            / plugin
            / rel,
        )
    )

    if bundled_default_path is not None:
        candidates.append(Candidate("bundled", Path(bundled_default_path)))

    return candidates


def resolve_customization_file(
    *,
    marketplace: str,
    plugin: str,
    rel_path: Path | str,
    repo_root: Path | str | None = None,
    bundled_default_path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | str | None = None,
) -> Candidate | None:
    """Resolve the first existing regular file in spec precedence order."""

    for candidate in candidate_paths(
        marketplace=marketplace,
        plugin=plugin,
        rel_path=rel_path,
        repo_root=repo_root,
        bundled_default_path=bundled_default_path,
        env=env,
        platform=platform,
        home=home,
    ):
        if candidate.path.is_file():
            return candidate
    return None


def _format_candidates(candidates: Iterable[Candidate]) -> str:
    return "\n".join(f"{candidate.source}\t{candidate.path}" for candidate in candidates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("marketplace")
    parser.add_argument("plugin")
    parser.add_argument("rel_path")
    parser.add_argument("--repo-root", help="Repository root to use for repo scope")
    parser.add_argument(
        "--start",
        default=".",
        help="Start path for .git-based repo-root discovery when --repo-root is omitted",
    )
    parser.add_argument("--no-repo", action="store_true", help="Skip repo-scope lookup")
    parser.add_argument("--bundled-default", help="Optional bundled default file path")
    parser.add_argument(
        "--print-candidates",
        action="store_true",
        help="Print all candidate paths instead of resolving",
    )
    parser.add_argument(
        "--with-source",
        action="store_true",
        help="Print '<source>\\t<path>' for the resolved file",
    )
    args = parser.parse_args(argv)

    if args.repo_root and args.no_repo:
        parser.error("--repo-root and --no-repo cannot be used together")

    repo_root = None
    if args.repo_root:
        repo_root = Path(args.repo_root)
    elif not args.no_repo:
        repo_root = find_repo_root(args.start)

    try:
        candidates = candidate_paths(
            marketplace=args.marketplace,
            plugin=args.plugin,
            rel_path=args.rel_path,
            repo_root=repo_root,
            bundled_default_path=args.bundled_default,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.print_candidates:
        print(_format_candidates(candidates))
        return 0

    for candidate in candidates:
        if candidate.path.is_file():
            if args.with_source:
                print(f"{candidate.source}\t{candidate.path}")
            else:
                print(candidate.path)
            return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
