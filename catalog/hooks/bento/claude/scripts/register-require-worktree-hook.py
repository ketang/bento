#!/usr/bin/env python3
"""SessionStart hook: register Bento's main-branch edit guard in Claude settings.

Idempotently adds PreToolUse hooks for Edit, Write, and NotebookEdit to
~/.claude/settings.json. Malformed settings and unexpected errors are silent
no-ops so session startup is never blocked.

Cross-runtime safety (bento-gs7): the script's only effect — patching
~/.claude/settings.json — is meaningful for Claude Code only. Codex wires
PreToolUse hooks through each plugin's own ``hooks/hooks.json`` and does not
read ~/.claude/settings.json. If the script is ever invoked from a Codex
SessionStart (whether because of a stale build, a manual install, or future
packaging mistake) it must no-op rather than plant a Codex plugin path into
the Claude settings file. The plugin root provided as ``argv[1]`` is the
authoritative runtime signal: Codex plugins live under ``~/.codex/``, Claude
plugins under ``~/.claude/``. We detect ``/.codex/`` in the plugin root path
and bail early.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


EDIT_TOOL_MATCHERS = ("Edit", "Write", "NotebookEdit")


def _looks_like_codex_plugin_root(plugin_root: str) -> bool:
    """True if ``plugin_root`` looks like a Codex plugin cache path.

    Codex installs plugins under ``~/.codex/plugins/cache/...``; Claude Code
    uses ``~/.claude/plugins/cache/...``. The presence of ``/.codex/`` in
    the path is the reliable runtime signal — substring rather than prefix
    so the check is independent of ``$HOME``. Posix path separators only:
    the script is Claude Code- and Codex-targeted and both runtimes pass
    forward-slash paths.
    """
    return "/.codex/" in plugin_root


def _usage() -> str:
    return (
        "register-require-worktree-hook: register Bento's Claude edit guard.\n\n"
        "Usage:\n"
        "  register-require-worktree-hook.py <plugin-root>\n"
        "  register-require-worktree-hook.py -h|--help\n"
    )


def _settings_path() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))) / ".claude" / "settings.json"


def _stable_symlink_path() -> Path:
    """Stable (version-independent) path for the require-worktree.sh symlink.

    Lives under ~/.claude/hooks/bento/ — a location owned by this script.
    Any pre-existing file or symlink there is overwritten unconditionally.
    """
    return (
        Path(os.environ.get("HOME", str(Path.home())))
        / ".claude"
        / "hooks"
        / "bento"
        / "require-worktree.sh"
    )


def _update_symlink(target: Path, stable: Path) -> None:
    """Atomically create or update stable to point at target.

    Uses mkstemp to get a unique temp name in the same directory, removes the
    placeholder file, creates a symlink at that path, then os.replace()s it
    onto stable — atomic on POSIX so concurrent sessions never see a missing
    or broken link mid-update.
    """
    stable.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".symlink-", dir=str(stable.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.unlink()
        os.symlink(target, tmp_path)
        os.replace(tmp_path, stable)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _load_settings(path: Path) -> dict | None:
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


def _entry_for(matcher: str, command: str) -> dict:
    return {
        "matcher": matcher,
        "hooks": [
            {
                "type": "command",
                "command": command,
            }
        ],
    }


def register(settings: dict, command: str) -> bool:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return False
    pre_tool_use = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre_tool_use, list):
        return False

    changed = False
    for matcher in EDIT_TOOL_MATCHERS:
        already_registered = any(
            isinstance(entry, dict)
            and entry.get("matcher") == matcher
            and any(
                isinstance(hook, dict)
                and hook.get("type") == "command"
                and hook.get("command") == command
                for hook in entry.get("hooks", [])
                if isinstance(entry.get("hooks"), list)
            )
            for entry in pre_tool_use
        )
        if already_registered:
            continue
        pre_tool_use.append(_entry_for(matcher, command))
        changed = True
    return changed


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    try:
        sys.stdin.read()
    except Exception:
        pass

    if len(argv) >= 2 and argv[1] in {"-h", "--help"}:
        sys.stdout.write(_usage())
        return 0
    if len(argv) < 2:
        return 0

    # Defense in depth (bento-gs7): the canonical build does not include this
    # script in the Codex plugin's hooks.json, but a stray Codex SessionStart
    # invocation (stale install, manual wiring) must not write a Codex plugin
    # path into ~/.claude/settings.json. Bail before touching the file.
    if _looks_like_codex_plugin_root(argv[1]):
        return 0

    try:
        plugin_root = Path(argv[1])
        target = plugin_root / "hooks" / "scripts" / "require-worktree.sh"
        stable = _stable_symlink_path()
        _update_symlink(target, stable)
        command = str(stable)
        settings_path = _settings_path()
        settings = _load_settings(settings_path)
        if settings is None:
            return 0
        if register(settings, command):
            _atomic_write_json(settings_path, settings)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
