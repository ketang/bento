#!/usr/bin/env python3
"""SessionStart hook: copies bento's bundled handoff template into the
home-scope agent-plugins path if it is missing. Idempotent and non-fatal."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".config"


def seed_handoff_template(plugin_root: Path) -> None:
    bundled = (
        plugin_root
        / "skills"
        / "handoff"
        / "references"
        / "templates"
        / "handoff.md"
    )
    if not bundled.is_file():
        return
    target = (
        _xdg_config_home()
        / "agent-plugins"
        / "bento"
        / "bento"
        / "handoff"
        / "template.md"
    )
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundled, target)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    try:
        sys.stdin.read()
    except Exception:
        pass
    if len(argv) < 2:
        return 0
    plugin_root = Path(argv[1])
    try:
        seed_handoff_template(plugin_root)
    except Exception:
        # Never block session start.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
