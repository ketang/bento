#!/usr/bin/env python3
"""PreToolUse/Bash hook: enforce land-work's review follow-up cap at `bd create`
(bento-c96u.9).

A `bd create` carrying the `review-followup` label is denied (exit 2) when:

1. its parent (`--parent P` or `--deps discovered-from:P`) already has another
   `review-followup` issue discovered from it (at most one follow-up per
   landing), or
2. its parent itself carries `review-followup` (no follow-ups of follow-ups).

Creates without the label are never touched. An operator waiver names the
parent in `.agent-mode.local`: `review_followup_waiver=<parent-id>[,<id>...]`.
`review_followup_guard=false` disables the check for the repo.

Reads the working directory from the payload `cwd`. Fails open on any
parse or `bd` error: it catches the common, unobfuscated case, not a
security boundary.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

LABEL = "review-followup"
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;&|\n]")
_WRAPPERS = frozenset({"rtk", "command", "env", "exec"})
_BD_GLOBAL_VALUE_FLAGS = frozenset({"--actor", "--db", "-C", "--directory", "--dolt-auto-commit"})


def _bd_create_args(command: str) -> list[list[str]]:
    """Argument lists (after `create`/`new`) of every `bd create` segment."""
    found: list[list[str]] = []
    for segment in _SEGMENT_SPLIT_RE.split(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        i = 0
        while i < len(tokens) and (
            re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]) or tokens[i] in _WRAPPERS
        ):
            i += 1
        if i >= len(tokens) or tokens[i] != "bd":
            continue
        i += 1
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 2 if tokens[i] in _BD_GLOBAL_VALUE_FLAGS else 1
        if i < len(tokens) and tokens[i] in ("create", "new"):
            found.append(tokens[i + 1:])
    return found


def _flag_values(args: list[str], long: str, short: str | None = None) -> list[str]:
    values: list[str] = []
    for i, tok in enumerate(args):
        if tok == long or (short and tok == short):
            if i + 1 < len(args):
                values.append(args[i + 1])
        elif tok.startswith(long + "="):
            values.append(tok.split("=", 1)[1])
        elif short and tok.startswith(short) and len(tok) > 2 and not tok.startswith("--"):
            values.append(tok[2:])
    return values


def _parents(args: list[str]) -> list[str]:
    parents = _flag_values(args, "--parent")
    for dep_list in _flag_values(args, "--deps"):
        for dep in dep_list.split(","):
            kind, _, ident = dep.strip().partition(":")
            if kind == "discovered-from" and ident:
                parents.append(ident)
    return parents


def _bd_json(args: list[str], cwd: str) -> list | dict | None:
    try:
        result = subprocess.run(
            ["bd", *args, "--json"], cwd=cwd, capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def _labels_of(parent: str, cwd: str) -> list[str] | None:
    data = _bd_json(["show", parent], cwd)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return list(data[0].get("labels") or [])
    return None


def _existing_followups(parent: str, cwd: str) -> list[str]:
    dependents = _bd_json(["dep", "list", parent, "--direction=up", "-t", "discovered-from"], cwd)
    labelled = _bd_json(["list", "--label", LABEL, "--all", "-n", "0"], cwd)
    if not isinstance(dependents, list) or not isinstance(labelled, list):
        return []
    labelled_ids = {d.get("id") for d in labelled if isinstance(d, dict)}
    return [d["id"] for d in dependents if isinstance(d, dict) and d.get("id") in labelled_ids]


def _agent_mode(repo_cwd: str) -> dict[str, str]:
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=repo_cwd,
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        text = (Path(root) / ".agent-mode.local").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            values[key.strip()] = value.strip()
    return values


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
            return 0
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        cwd = payload.get("cwd") or ""
        if not isinstance(command, str) or not cwd or "bd" not in command:
            return 0

        creates = [
            args for args in _bd_create_args(command)
            if LABEL in {
                label.strip()
                for value in _flag_values(args, "--labels", "-l")
                for label in value.split(",")
            }
        ]
        if not creates:
            return 0

        mode = _agent_mode(cwd)
        if mode.get("review_followup_guard") == "false":
            return 0
        waived = {w.strip() for w in mode.get("review_followup_waiver", "").split(",")}

        for args in creates:
            for parent in _parents(args):
                if parent in waived:
                    continue
                if LABEL in (_labels_of(parent, cwd) or []):
                    print(
                        f"Blocked: parent {parent} is itself a {LABEL} issue; do not file "
                        "follow-ups of follow-ups. Surface the findings to the operator in the "
                        "landing report, or ask the operator to waive it by adding "
                        f"'review_followup_waiver={parent}' to .agent-mode.local.",
                        file=sys.stderr,
                    )
                    return 2
                existing = _existing_followups(parent, cwd)
                if existing:
                    print(
                        f"Blocked: {parent} already has a {LABEL} follow-up ({existing[0]}); "
                        "file at most one follow-up per landing. Add the finding to that "
                        "issue's checklist instead, or ask the operator to waive it by adding "
                        f"'review_followup_waiver={parent}' to .agent-mode.local.",
                        file=sys.stderr,
                    )
                    return 2
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
