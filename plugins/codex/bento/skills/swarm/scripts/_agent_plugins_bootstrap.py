"""Adds launch-work/scripts to sys.path so its modules are importable.

Duplicated verbatim into every skill scripts/ dir that needs a launch-work
module (agent_plugins_resolver, process_group, lifecycle_extensions, ...) but
lives outside launch-work/scripts (same convention as this repo's per-skill
git_state.py copies). If launch-work/scripts ever moves, grep for
`_launch_work_scripts_dir` to find and update every copy.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _launch_work_scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "launch-work" / "scripts"


def ensure_launch_work_scripts_importable() -> None:
    """Make `import <launch-work module>` work from a sibling skill script."""
    path_str = str(_launch_work_scripts_dir())
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
