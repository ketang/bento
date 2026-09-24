#!/usr/bin/env python3
"""Stop hook: block the swarm lead from ending while ready branches are unlanded.

Reads the queue written by the swarm skill's ``swarm-landing-queue.py``
(``$(git rev-parse --git-common-dir)/bento/landing-queue.json``) and exits 2
when it holds non-deferred, still-unmerged entries whose ``lead_agent`` matches
this hook's own claude/codex ancestor process ({pid, start_time}). Other
sessions, deferred-only or empty queues, re-entrant Stop invocations
(``stop_hook_active``) and a one-turn hold marker
(``bento-check-landing-queue-hold-<session_id>`` under ``$XDG_RUNTIME_DIR`` or
/tmp, consumed on use) all exit 0. The working directory comes from the ``cwd``
field of the stdin JSON payload, never ``$PWD``. Fails open on any error.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HOLD_PREFIX = "bento-check-landing-queue-hold-"
AGENT_COMMS = ("claude", "codex")


def agent_ancestor(pid: int | None = None) -> dict | None:
    pid = os.getpid() if pid is None else pid
    for _ in range(64):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            comm = Path(f"/proc/{pid}/comm").read_text().strip()
        except OSError:
            return None
        fields = stat.rsplit(")", 1)[1].split()
        if comm in AGENT_COMMS:
            return {"pid": pid, "start_time": int(fields[19])}
        pid = int(fields[1])
        if pid <= 1:
            return None
    return None


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def is_landed(cwd: str, branch: str) -> bool:
    """True when the branch is gone or already merged into the primary branch."""
    if _git(cwd, "rev-parse", "--verify", "-q", f"refs/heads/{branch}").returncode != 0:
        return True
    head = _git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    candidates = [head.stdout.strip()] if head.returncode == 0 else []
    candidates += ["main", "master"]
    for primary in candidates:
        if _git(cwd, "rev-parse", "--verify", "-q", primary).returncode == 0:
            return _git(cwd, "merge-base", "--is-ancestor", branch, primary).returncode == 0
    return False


def pending_entries(cwd: str) -> list[dict]:
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common.returncode != 0:
        return []
    try:
        entries = json.loads((Path(common.stdout.strip()) / "bento" / "landing-queue.json").read_text())["entries"]
    except (OSError, ValueError, KeyError):
        return []
    me = agent_ancestor()
    if me is None:
        return []
    return [
        e for e in entries
        if not e.get("deferred") and e.get("lead_agent") == me and not is_landed(cwd, e["branch"])
    ]


def consume_hold(session_id: str) -> bool:
    if not session_id or any(not (c.isalnum() or c in "._-") for c in session_id) or set(session_id) <= {"."}:
        return False
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime and Path(runtime).is_absolute() and Path(runtime).is_dir() else Path("/tmp")
    try:
        (base / f"{HOLD_PREFIX}{session_id}").unlink()
    except OSError:
        return False
    return True


def evaluate(hook_input: dict) -> str | None:
    if hook_input.get("stop_hook_active"):
        return None
    cwd = hook_input.get("cwd") or ""
    if not cwd or not os.path.isdir(cwd):
        return None
    entries = pending_entries(cwd)
    if not entries:
        return None
    session_id = hook_input.get("session_id") or ""
    if consume_hold(session_id):
        return None
    branches = ", ".join(e["branch"] for e in entries)
    return (
        f"{len(entries)} branches are ready to land: {branches}. Land them, or run "
        "swarm-landing-queue.py defer <branch> --reason ... "
        f"(one-turn hold: create '{HOLD_PREFIX}{session_id}' under $XDG_RUNTIME_DIR or /tmp).\n"
    )


def main() -> int:
    try:
        reason = evaluate(json.load(sys.stdin))
    except Exception:
        return 0
    if reason:
        sys.stderr.write(reason)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
