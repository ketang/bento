#!/usr/bin/env python3
"""Stop hook: block ending a session with uncommitted or unpushed work.

Blocks (exit 2) when the session cwd's git repo has a dirty working tree
(``git status --porcelain`` non-empty) or has local commits ahead of its
upstream (``git rev-list @{u}..HEAD --count`` > 0). The blocking reason on
stderr names the branch and the counts so it is actionable.

A branch with no upstream is treated as a warning, not a block: worktree flows
that have not pushed a first commit yet must not be trapped, so a clean
no-upstream branch passes. A dirty tree still blocks regardless of upstream.

Silent no-op cases (exit 0): no/invalid cwd, a non-git cwd, a repo that opts
out via ``require_pushed=false`` in ``.agent-mode.local``, and re-entrant Stop
invocations (``stop_hook_active``) so a block never loops forever.

Claude Code runs hook processes from $HOME, not the project root, so the
session directory is read from the stdin JSON payload's ``cwd`` field, never
from $PWD or the process CWD.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def _git(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", root, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def repo_root(cwd: str) -> str | None:
    result = _git(cwd, "rev-parse", "--show-toplevel")
    root = result.stdout.strip()
    return root if result.returncode == 0 and root else None


def is_suppressed(root: str) -> bool:
    """True when .agent-mode.local sets require_pushed=false."""
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
        if key.strip() == "require_pushed" and value.strip() == "false":
            return True
    return False


def current_branch(root: str) -> str:
    return _git(root, "branch", "--show-current").stdout.strip()


def is_dirty(root: str) -> bool:
    result = _git(root, "status", "--porcelain")
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def has_upstream(root: str) -> bool:
    result = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return result.returncode == 0


def ahead_count(root: str) -> int:
    result = _git(root, "rev-list", "@{u}..HEAD", "--count")
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def block_reason(hook_input: dict) -> str | None:
    """Return a blocking stderr message, or None to allow the stop."""
    if hook_input.get("stop_hook_active"):
        return None

    cwd = hook_input.get("cwd") or ""
    if not cwd or not os.path.isdir(cwd):
        return None

    root = repo_root(cwd)
    if root is None:
        return None

    if is_suppressed(root):
        return None

    problems: list[str] = []
    if is_dirty(root):
        problems.append("uncommitted changes")

    # A missing upstream is a warning, not a block, so worktree flows that have
    # not pushed a first commit are not trapped. Only count ahead commits when
    # an upstream exists.
    if has_upstream(root):
        ahead = ahead_count(root)
        if ahead > 0:
            noun = "commit" if ahead == 1 else "commits"
            problems.append(f"{ahead} unpushed {noun}")

    if not problems:
        return None

    branch = current_branch(root) or "(detached HEAD)"
    joined = " and ".join(problems)
    return (
        f"Session end blocked: branch '{branch}' has {joined}.\n"
        "Commit and push your work before ending the session. "
        "To suppress this check for this repo, add 'require_pushed=false' to "
        ".agent-mode.local.\n"
    )


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        # Never break session stop on a malformed payload.
        return 0
    try:
        reason = block_reason(hook_input)
    except Exception:
        # Never break session stop on an unexpected git/filesystem error.
        return 0
    if reason:
        # Exit code 2 is the documented Stop blocking signal for Claude Code:
        # the stderr message is fed back to the model. Exit 1 is a non-blocking
        # failure and lets the stop proceed, so the hook must use 2 to block.
        sys.stderr.write(reason)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
