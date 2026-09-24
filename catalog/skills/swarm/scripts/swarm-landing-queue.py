#!/usr/bin/env python3
"""Persistent landing queue for the swarm lead: add, pop, list, defer, clear.

The queue lives at ``$(git rev-parse --git-common-dir)/bento/landing-queue.json``
so every worktree of a repo shares it. Writes are atomic (temp file + rename)
and serialized by an flock on a sibling lock file. Each entry records the
lead's agent process ({pid, start_time} of the nearest ``claude``/``codex``
ancestor) so the Stop hook can block only the lead session.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

AGENT_COMMS = ("claude", "codex")


def agent_ancestor(pid: int | None = None) -> dict | None:
    """Nearest ancestor whose comm is claude or codex, as {pid, start_time}."""
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


def queue_path(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=cwd, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"swarm-landing-queue: not a git repository: {cwd}")
    return Path(result.stdout.strip()) / "bento" / "landing-queue.json"


def load(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text())["entries"]
    except FileNotFoundError:
        return []


def store(path: Path, entries: list[dict]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".landing-queue-")
    with os.fdopen(fd, "w") as fh:
        json.dump({"entries": entries}, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mutate(path: Path, fn) -> int:
    """Run fn(entries) -> (entries, exit_code) under the queue lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries, code = fn(load(path))
        if code == 0:
            store(path, entries)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(prog="swarm-landing-queue")
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("branch")
    add.add_argument("--worktree", required=True)
    add.add_argument("--tracker-id", default="")
    add.add_argument("--gate-summary", default="")
    pop = sub.add_parser("pop")
    pop.add_argument("branch")
    defer = sub.add_parser("defer")
    defer.add_argument("branch")
    defer.add_argument("--reason", required=True)
    sub.add_parser("list")
    clear = sub.add_parser("clear")
    clear.add_argument("--all", action="store_true")
    clear.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    path = queue_path(Path.cwd())
    if args.cmd == "list":
        json.dump({"entries": load(path)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    def missing(branch: str) -> int:
        print(f"swarm-landing-queue: {branch} is not queued", file=sys.stderr)
        return 1

    if args.cmd == "add":
        entry = {
            "branch": args.branch,
            "worktree": str(Path(args.worktree).resolve()),
            "tracker_id": args.tracker_id,
            "gate_summary": args.gate_summary,
            "signalled_at": now(),
            "lead_agent": agent_ancestor(),
        }
        return mutate(path, lambda es: ([e for e in es if e["branch"] != args.branch] + [entry], 0))
    if args.cmd == "pop":
        def do_pop(es):
            rest = [e for e in es if e["branch"] != args.branch]
            return (rest, 0) if len(rest) != len(es) else (es, missing(args.branch))
        return mutate(path, do_pop)
    if args.cmd == "defer":
        def do_defer(es):
            hit = [e for e in es if e["branch"] == args.branch]
            if not hit:
                return es, missing(args.branch)
            hit[0]["deferred"] = {"reason": args.reason, "at": now()}
            return es, 0
        return mutate(path, do_defer)
    if not (args.all and args.yes):
        print("swarm-landing-queue: clear requires --all --yes (operator use only)", file=sys.stderr)
        return 2
    return mutate(path, lambda es: ([], 0))


if __name__ == "__main__":
    raise SystemExit(main())
