"""Adds launch-work/scripts to sys.path so agent_plugins_resolver is importable.

Duplicated verbatim into every skill scripts/ dir that needs
agent_plugins_resolver but lives outside launch-work/scripts (same convention
as this repo's per-skill git_state.py copies). If launch-work/scripts ever
moves, grep for `_launch_work_scripts_dir` to find and update every copy.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _launch_work_scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "launch-work" / "scripts"


def ensure_agent_plugins_resolver_importable() -> None:
    """Make `import agent_plugins_resolver` work from a sibling skill script."""
    path_str = str(_launch_work_scripts_dir())
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
