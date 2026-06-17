#!/usr/bin/env python3
"""SessionStart hook: snapshots the working tree's untracked files so the
companion Stop hook (hygiene-check.py) can warn about strays that appeared
during the session.

Resolves the git repository that contains the session cwd and writes the set
of untracked paths reported by
`git status --porcelain=v1 --untracked-files=all` to
<cache>/bento/hygiene-baseline-<session_id>.txt, one repo-root-relative path
per line.

gitignored files never appear in that output, so build outputs and other
ignored artifacts are excluded from the baseline and from later warnings.

Never blocks session start."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Session ids are interpolated into a filename, so only allow characters that
# cannot escape the cache directory. All-dot ids are rejected as path-special.
SESSION_ID_RE = re.compile(r"\A[A-Za-z0-9_.-]+\Z")

BASELINE_PREFIX = "hygiene-baseline-"


def cache_root(home: Path | None = None, env: dict | None = None) -> Path:
    """Resolve the bento cache directory, honoring XDG_CACHE_HOME."""
    environ = os.environ if env is None else env
    xdg = environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else (home or Path.home()) / ".cache"
    return base / "bento"


def baseline_path(session_id: str, home: Path | None = None, env: dict | None = None) -> Path:
    return cache_root(home, env) / f"{BASELINE_PREFIX}{session_id}.txt"


def repo_root(cwd: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    root = result.stdout.strip()
    return root if result.returncode == 0 and root else None


def untracked_files(root: str) -> list[str]:
    """Return untracked (?? ) paths reported by git status, relative to root."""
    result = subprocess.run(
        ["git", "-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line[3:] for line in result.stdout.splitlines() if line.startswith("?? ")]


def run(
    hook_input: dict,
    home: Path | None = None,
    env: dict | None = None,
) -> None:
    session_id = hook_input.get("session_id", "")
    if not session_id or not SESSION_ID_RE.match(session_id) or set(session_id) <= {"."}:
        return

    cwd = hook_input.get("cwd") or ""
    if not cwd or not os.path.isdir(cwd):
        return

    root = repo_root(cwd)
    if root is None:
        return

    paths = untracked_files(root)

    target = baseline_path(session_id, home, env)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{p}\n" for p in paths), encoding="utf-8")


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
        run(hook_input)
    except Exception:
        # Never block session start.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
