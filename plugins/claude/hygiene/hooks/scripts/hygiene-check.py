#!/usr/bin/env python3
"""Stop hook: warns when untracked files appeared during the session that were
not present at session start (see the companion SessionStart hook
hygiene-baseline.py).

Compares the current untracked set against the per-session baseline and, if new
non-gitignored untracked paths exist, emits a blocking Stop decision listing
them with a clean-or-ignore instruction. The decision is advisory-but-loud: it
surfaces the strays to the model but never deletes anything.

Suppression: add `hygiene_check=false` to `.agent-mode.local` in the repo root
(same mechanism require-worktree.sh uses for `require_worktree=false`).

Stays silent when:
- the working tree is unchanged (no new untracked files),
- gitignored files appear (they never show in porcelain output),
- no baseline exists (e.g. a resumed session that started before this hook),
- the check is suppressed, or
- the Stop hook is already active (avoids re-blocking loops)."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SESSION_ID_RE = re.compile(r"\A[A-Za-z0-9_.-]+\Z")

BASELINE_PREFIX = "hygiene-baseline-"


def cache_root(home: Path | None = None, env: dict | None = None) -> Path:
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
    result = subprocess.run(
        ["git", "-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line[3:] for line in result.stdout.splitlines() if line.startswith("?? ")]


def is_suppressed(root: str) -> bool:
    """True when .agent-mode.local sets hygiene_check=false."""
    config = Path(root) / ".agent-mode.local"
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key.strip() == "hygiene_check" and value.strip() == "false":
            return True
    return False


def warning_message(new_paths: list[str]) -> str:
    listing = "\n".join(f"  - {p}" for p in new_paths)
    count = len(new_paths)
    noun = "file" if count == 1 else "files"
    return (
        f"Working-tree hygiene: {count} new untracked {noun} appeared during this "
        f"session and {'is' if count == 1 else 'are'} not covered by .gitignore:\n"
        f"{listing}\n"
        "Clean them up (remove or move them) or add them to .gitignore before "
        "ending the session. To suppress this check for this repo, add "
        "'hygiene_check=false' to .agent-mode.local."
    )


def evaluate(
    hook_input: dict,
    home: Path | None = None,
    env: dict | None = None,
) -> dict | None:
    """Return a Stop decision dict to emit, or None to stay silent."""
    if hook_input.get("stop_hook_active"):
        return None

    session_id = hook_input.get("session_id", "")
    if not session_id or not SESSION_ID_RE.match(session_id) or set(session_id) <= {"."}:
        return None

    cwd = hook_input.get("cwd") or ""
    if not cwd or not os.path.isdir(cwd):
        return None

    root = repo_root(cwd)
    if root is None:
        return None

    if is_suppressed(root):
        return None

    baseline_file = baseline_path(session_id, home, env)
    try:
        baseline = set(baseline_file.read_text(encoding="utf-8").splitlines())
    except OSError:
        # No baseline (e.g. resumed session): cannot diff, so stay silent.
        return None

    current = untracked_files(root)
    new_paths = sorted(p for p in current if p not in baseline)
    if not new_paths:
        return None

    return {"decision": "block", "reason": warning_message(new_paths)}


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
        decision = evaluate(hook_input)
    except Exception:
        # Never break session stop.
        return 0
    if decision is not None:
        json.dump(decision, sys.stdout)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
