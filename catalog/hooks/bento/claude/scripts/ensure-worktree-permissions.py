#!/usr/bin/env python3
"""SessionStart hook: ensure bento worktree paths are pre-authorized.

Adds the documented default worktree root and the parent directories of any
linked worktrees in the current repo to permissions.additionalDirectories in
~/.claude/settings.json. Idempotent. Failures are non-fatal: a malformed
settings file or any unexpected error must never break the user's session."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_WORKTREE_ROOT_REL = ".local/share/worktrees"


def _settings_path() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))) / ".claude" / "settings.json"


def _load_settings(path: Path) -> dict | None:
    """Return parsed settings, {} if missing, or None if malformed."""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _is_covered(candidate: str, existing: list[str]) -> bool:
    """True if candidate is already covered by an existing entry — same path
    or a parent path."""
    candidate_path = Path(candidate).resolve()
    for entry in existing:
        try:
            entry_path = Path(os.path.expanduser(entry)).resolve()
        except (OSError, ValueError):
            continue
        if candidate_path == entry_path:
            return True
        try:
            candidate_path.relative_to(entry_path)
            return True
        except ValueError:
            continue
    return False


def _git_worktree_parents(cwd: Path) -> list[str]:
    """Return parent directories of linked (non-primary) worktrees in cwd's
    repo, deduplicated and order-preserved. Empty list if cwd is not in a
    git repo."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []

    paths: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(line.split(" ", 1)[1])

    if len(paths) <= 1:
        return []

    primary = paths[0]
    parents: list[str] = []
    seen: set[str] = set()
    for path in paths[1:]:
        parent = str(Path(path).parent.resolve())
        if parent == str(Path(primary).resolve()):
            continue
        if parent in seen:
            continue
        seen.add(parent)
        parents.append(parent)
    return parents


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".settings-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _payload_cwd() -> Path | None:
    """Read the project directory from the stdin JSON payload's `cwd` field.

    Claude Code spawns hook processes from $HOME, so the process CWD is never
    the project root; the project directory arrives only in the payload. Return
    None when stdin is absent, malformed, or lacks a usable `cwd`."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    if not raw or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return None
    return Path(cwd)


def main() -> int:
    try:
        # Read the project directory from the payload; this also drains stdin so
        # the hook protocol is satisfied.
        payload_cwd = _payload_cwd()

        settings_path = _settings_path()
        settings = _load_settings(settings_path)
        if settings is None:
            return 0

        home = Path(os.environ.get("HOME", str(Path.home())))
        default_root = str((home / DEFAULT_WORKTREE_ROOT_REL).resolve())

        candidates: list[str] = [default_root]
        # Prefer the payload cwd (the real project dir); fall back to the
        # process cwd only when the payload lacks one.
        cwd = payload_cwd
        if cwd is None:
            try:
                cwd = Path.cwd()
            except OSError:
                cwd = None
        if cwd is not None:
            for parent in _git_worktree_parents(cwd):
                if parent not in candidates:
                    candidates.append(parent)

        permissions = settings.setdefault("permissions", {})
        if not isinstance(permissions, dict):
            return 0
        existing = permissions.setdefault("additionalDirectories", [])
        if not isinstance(existing, list):
            return 0

        changed = False
        for candidate in candidates:
            if _is_covered(candidate, existing):
                continue
            existing.append(candidate)
            changed = True

        if changed:
            _atomic_write_json(settings_path, settings)
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
