#!/usr/bin/env python3
"""PreToolUse/Bash hook: enforce land-work's review follow-up cap at `bd create`
(bento-c96u.9).

A `bd create` that carries the `review-followup` label is denied (exit 2) when:

1. its parent (`--parent P` or `--deps discovered-from:P`) already has another
   `review-followup` child or discovered-from issue (at most one follow-up per
   landing), or
2. its parent itself carries `review-followup` (no follow-ups of follow-ups).

`bd create --parent Q` inherits Q's labels unless `--no-inherit-labels` is
given (verified against a scratch DB), so such a create counts as labelled
when Q carries `review-followup`. Creates without the label are never touched.

An operator waiver names the parent in `.agent-mode.local`:
`review_followup_waiver=<parent-id>[,<id>...]`; agents must never write it
themselves. `review_followup_guard=false` disables the check for the repo.

Best-effort, not a security boundary: the command is tokenized once (quotes
and heredoc bodies respected, `bash -c` unwrapped) but obfuscated shell can
evade it, a lone quoted `';'`/`'&&'` argument is indistinguishable from an
operator, and it fails open when `bd` errors, times out, or is missing. The
shell segmenting is duplicated from the other guards; a shared module is out
of scope. Reads the working directory from the payload `cwd`.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

LABEL = "review-followup"
_OPERATOR_CHARS = frozenset(";&|()\n")
_WRAPPERS = frozenset({"rtk", "command", "env", "exec"})
_SHELLS = frozenset({"bash", "sh", "zsh"})
_BD_GLOBAL_VALUE_FLAGS = frozenset({"--actor", "--db", "-C", "--directory", "--dolt-auto-commit"})
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_BD_TIMEOUT_SECONDS = 10


def _strip_heredoc_bodies(command: str) -> str:
    out: list[str] = []
    terminator: str | None = None
    for line in command.split("\n"):
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        out.append(line)
        match = _HEREDOC_RE.search(line)
        if match:
            terminator = match.group(2)
    return "\n".join(out)


def _segments(command: str) -> list[list[str]]:
    """Split a command into argv lists on unquoted ; && || | & ( ) newline."""
    lexer = shlex.shlex(_strip_heredoc_bodies(command), posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    segments: list[list[str]] = [[]]
    for token in lexer:
        if set(token) <= _OPERATOR_CHARS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [seg for seg in segments if seg]


def _bd_create_args(command: str, depth: int = 0) -> list[list[str]]:
    """Argument lists (after `create`/`new`) of every `bd create` segment,
    including ones inside `bash -c "..."`."""
    found: list[list[str]] = []
    for tokens in _segments(command):
        i = 0
        while i < len(tokens) and (
            re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]) or tokens[i] in _WRAPPERS
        ):
            i += 1
        if i >= len(tokens):
            continue
        if tokens[i] in _SHELLS and depth < 3 and "-c" in tokens[i + 1:]:
            j = tokens.index("-c", i + 1)
            if j + 1 < len(tokens):
                found.extend(_bd_create_args(tokens[j + 1], depth + 1))
            continue
        if tokens[i] != "bd":
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
            timeout=_BD_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
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
    """Review-followup issues discovered from, or children of, `parent`.
    Fails open (returns []) when either `bd` call fails."""
    dependents = _bd_json(["dep", "list", parent, "--direction=up"], cwd)
    labelled = _bd_json(["list", "--label", LABEL, "--all", "-n", "0"], cwd)
    if not isinstance(dependents, list) or not isinstance(labelled, list):
        return []
    labelled_ids = {d.get("id") for d in labelled if isinstance(d, dict)}
    return [
        d["id"] for d in dependents
        if isinstance(d, dict)
        and d.get("dependency_type") in ("discovered-from", "parent-child")
        and d.get("id") in labelled_ids
    ]


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

        creates = _bd_create_args(command)
        if not creates:
            return 0

        mode = _agent_mode(cwd)
        if mode.get("review_followup_guard") == "false":
            return 0
        waived = {w.strip() for w in mode.get("review_followup_waiver", "").split(",")}

        for args in creates:
            explicit = LABEL in {
                label.strip()
                for value in _flag_values(args, "--labels", "-l")
                for label in value.split(",")
            }
            inherits = "--no-inherit-labels" not in args
            hierarchical = _flag_values(args, "--parent")
            for parent in _parents(args):
                if parent in waived or not (explicit or (inherits and parent in hierarchical)):
                    continue
                parent_is_followup = LABEL in (_labels_of(parent, cwd) or [])
                if not explicit and not parent_is_followup:
                    continue  # label would only be inherited from a non-followup parent
                if parent_is_followup:
                    print(
                        f"Blocked: parent {parent} is itself a {LABEL} issue; do not file "
                        "follow-ups of follow-ups. Surface the findings to the operator in the "
                        "landing report; only the operator may waive this.",
                        file=sys.stderr,
                    )
                    return 2
                existing = _existing_followups(parent, cwd)
                if existing:
                    print(
                        f"Blocked: {parent} already has a {LABEL} follow-up ({existing[0]}); "
                        "file at most one follow-up per landing. Add the finding to that "
                        "issue's checklist instead; only the operator may waive this.",
                        file=sys.stderr,
                    )
                    return 2
    except Exception as exc:
        print(f"bd-review-followup-guard: failing open: {exc!r}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
