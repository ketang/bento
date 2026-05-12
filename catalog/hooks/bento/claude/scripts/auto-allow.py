#!/usr/bin/env python3
"""PreToolUse/Bash hook: auto-allow Bash invocations of Python scripts shipped
by this plugin, so users are not re-prompted for the plugin's own bundled
helpers after the plugin-install trust check.

Usage (as wired from hooks.json):
    auto-allow.py <plugin-name> <plugin-root>

Decision logic:
  * Hard-reject if the command contains shell sequencing or substitution
    metacharacters (&&, ||, ;, $(, backtick, newline).
  * Tokenize via shlex; split into a head and a benign tail at the first
    redirect or pipe token.
  * The tail must be a small allowlist: any combination of safe single-token
    redirects (2>&1, >/dev/null, 2>/dev/null, &>/dev/null) optionally
    followed by exactly one pipe to head|tail|cat|less|wc with numeric
    pagination args.
  * The head may be the script directly, or prefixed with python/python3/
    pythonX.Y/uv run/uvx and a small set of safe interpreter flags.
  * The resolved script must be a regular .py file under either the plugin
    root or the plugin's own source repo (detected by an ancestor that has
    .claude-plugin/marketplace.json and a matching plugins/claude/<name>/
    .claude-plugin/plugin.json).

On allow, prints the PreToolUse permission-decision JSON on stdout.
On no-decision, exits silently except for a one-line diagnostic on stderr.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path


HARD_REJECT_SENTINELS = ("&&", "||", ";", "$(", "`", "\n")

TAIL_START_TOKENS = {"|", ">", "<", "2>", "&>"}

ALLOWED_REDIRECT_TOKENS = {"2>&1", ">/dev/null", "2>/dev/null", "&>/dev/null"}

PYTHON_INTERPRETER_RE = re.compile(r"^python(\d+(\.\d+)?)?$")

SAFE_INTERPRETER_FLAGS = {"-u", "-I", "-S", "-O", "-OO", "-B"}

ALLOWED_READERS = {"head", "tail", "cat", "less", "wc"}

READER_FLAG_RE = re.compile(r"^(-[lwcn]|-\d+|--lines=\d+|--bytes=\d+|\d+)$")

SOURCE_REPO_WALK_DEPTH = 8


def _hard_reject(command: str) -> str | None:
    for token in HARD_REJECT_SENTINELS:
        if token in command:
            return f"compound command (contains {token!r})"
    return None


def _split_head_tail(tokens: list[str]) -> tuple[list[str], list[str]]:
    for i, tok in enumerate(tokens):
        if tok in TAIL_START_TOKENS or tok in ALLOWED_REDIRECT_TOKENS:
            return tokens[:i], tokens[i:]
    return tokens, []


def _validate_tail(tail: list[str]) -> str | None:
    i = 0
    while i < len(tail) and tail[i] in ALLOWED_REDIRECT_TOKENS:
        i += 1
    if i == len(tail):
        return None
    tok = tail[i]
    if tok != "|":
        return f"unsupported redirect: {tok!r}"
    i += 1
    if i >= len(tail):
        return "pipe with no command"
    reader = tail[i]
    if reader not in ALLOWED_READERS:
        return f"unsupported tail command: {reader!r}"
    i += 1
    while i < len(tail):
        arg = tail[i]
        if arg in TAIL_START_TOKENS or arg in ALLOWED_REDIRECT_TOKENS:
            return f"unsupported chained tail starting at {arg!r}"
        if not READER_FLAG_RE.match(arg):
            return f"unsupported reader flag: {arg!r}"
        i += 1
    return None


def _strip_interpreter_prefix(tokens: list[str]) -> tuple[list[str], str]:
    """If tokens start with a recognized interpreter, advance past the
    interpreter and any safe flags. Returns (remaining_tokens, reason).
    On success reason is empty; on rejection reason is non-empty and the
    returned tokens should be ignored.
    """
    if not tokens:
        return tokens, "empty tokens"
    base = os.path.basename(tokens[0])
    if PYTHON_INTERPRETER_RE.match(base):
        idx = 1
        while idx < len(tokens):
            tok = tokens[idx]
            if tok in SAFE_INTERPRETER_FLAGS:
                idx += 1
                continue
            if tok.startswith("-"):
                return tokens, f"unsupported interpreter flag: {tok!r}"
            return tokens[idx:], ""
        return tokens, "interpreter with no script"
    if base in {"uv", "uvx"}:
        idx = 1
        if base == "uv":
            if idx >= len(tokens) or tokens[idx] != "run":
                sub = tokens[idx] if idx < len(tokens) else ""
                return tokens, f"unsupported uv subcommand: {sub!r}"
            idx += 1
        if idx >= len(tokens):
            return tokens, "uv with no script"
        if tokens[idx].startswith("-"):
            return tokens, f"unsupported uv flag: {tokens[idx]!r}"
        return tokens[idx:], ""
    return tokens, ""


def _find_source_repo_root(script_path: Path, plugin_name: str) -> Path | None:
    parent = script_path.parent
    for _ in range(SOURCE_REPO_WALK_DEPTH):
        marketplace = parent / ".claude-plugin" / "marketplace.json"
        plugin_meta = (
            parent / "plugins" / "claude" / plugin_name / ".claude-plugin" / "plugin.json"
        )
        if marketplace.is_file() and plugin_meta.is_file():
            try:
                meta = json.loads(plugin_meta.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
            if meta.get("name") == plugin_name:
                return parent
        if parent.parent == parent:
            return None
        parent = parent.parent
    return None


def _check_containment(
    resolved: Path, plugin_root: Path, plugin_name: str
) -> tuple[Path | None, bool, str]:
    """Return (matched_root, via_source_repo, error_reason)."""
    root = Path(os.path.realpath(str(plugin_root)))
    try:
        resolved.relative_to(root)
        return root, False, ""
    except ValueError:
        pass
    source_root = _find_source_repo_root(resolved, plugin_name)
    if source_root is not None:
        return source_root, True, ""
    return None, False, f"resolved path {resolved!s} is outside plugin root {root!s}"


def decide(
    command: str,
    plugin_name: str,
    plugin_root: Path,
) -> tuple[dict | None, str]:
    """Return (decision_dict_or_None, diagnostic_reason)."""
    command = command.strip()
    if not command:
        return None, "empty command"

    hard_reason = _hard_reject(command)
    if hard_reason:
        return None, hard_reason

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        return None, f"could not parse command: {exc}"
    if not tokens:
        return None, "empty command"

    head, tail = _split_head_tail(tokens)
    if not head:
        return None, "no head command"
    tail_reason = _validate_tail(tail)
    if tail_reason:
        return None, tail_reason

    head_after_interp, interp_reason = _strip_interpreter_prefix(head)
    if interp_reason:
        return None, interp_reason
    if not head_after_interp:
        return None, "no script after interpreter"

    first = head_after_interp[0]
    if not first.endswith(".py"):
        return None, f"first token is not a .py script: {first!r}"

    resolved = Path(os.path.realpath(first))
    if not resolved.exists():
        return None, f"script not found: {resolved!s}"
    if not resolved.is_file():
        return None, f"script is not a regular file: {resolved!s}"

    matched_root, via_source, contain_err = _check_containment(
        resolved, plugin_root, plugin_name
    )
    if matched_root is None:
        return None, contain_err

    rel = resolved.relative_to(matched_root)
    via = " via source repo" if via_source else ""
    decision = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": (
                f"auto-approved by {plugin_name} plugin{via}: {rel}"
            ),
        }
    }
    return decision, f"allowed{via}: {rel}"


def main(argv=None, stdin=None, stdout=None, stderr=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    if len(argv) != 3:
        print(
            f"auto-allow: expected 2 args (plugin-name, plugin-root); got {len(argv) - 1}",
            file=stderr,
        )
        return 0

    plugin_name = argv[1]
    plugin_root = Path(argv[2])

    try:
        payload = json.load(stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"auto-allow: invalid hook input JSON: {exc}", file=stderr)
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    decision, reason = decide(command, plugin_name, plugin_root)

    print(f"auto-allow[{plugin_name}]: {reason}", file=stderr)

    if decision is not None:
        json.dump(decision, stdout)
        stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
