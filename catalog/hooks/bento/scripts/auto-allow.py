#!/usr/bin/env python3
"""PreToolUse/Bash hook: auto-allow Bash invocations of Python scripts shipped
by this plugin, so users are not re-prompted for the plugin's own bundled
helpers after the plugin-install trust check.

Usage (as wired from hooks.json):
    auto-allow.py <plugin-name> <plugin-root>

Decision logic:
  * Command must be a single simple invocation (no shell metacharacters).
  * argv[0] must resolve (via realpath) to a regular file inside plugin-root.
  * That file must have a .py suffix.

On allow, prints the PreToolUse permission-decision JSON on stdout.
On no-decision, exits silently except for a one-line diagnostic on stderr.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path


COMPOUND_SENTINELS = ("&&", "||", ";", "|", "$(", "`", ">", "<", "\n")


def _reject_compound(command: str) -> str | None:
    for token in COMPOUND_SENTINELS:
        if token in command:
            return f"compound command (contains {token!r})"
    return None


def decide(
    command: str,
    plugin_name: str,
    plugin_root: Path,
) -> tuple[dict | None, str]:
    """Return (decision_dict_or_None, diagnostic_reason)."""
    command = command.strip()
    if not command:
        return None, "empty command"

    compound_reason = _reject_compound(command)
    if compound_reason:
        return None, compound_reason

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        return None, f"could not parse command: {exc}"
    if not tokens:
        return None, "empty command"

    first = tokens[0]
    if not first.endswith(".py"):
        return None, f"first token is not a .py script: {first!r}"

    resolved = Path(os.path.realpath(first))
    root = Path(os.path.realpath(str(plugin_root)))

    try:
        resolved.relative_to(root)
    except ValueError:
        return None, f"resolved path {resolved!s} is outside plugin root {root!s}"

    if not resolved.exists():
        return None, f"script not found: {resolved!s}"
    if not resolved.is_file():
        return None, f"script is not a regular file: {resolved!s}"

    decision = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": (
                f"auto-approved by {plugin_name} plugin: "
                f"{resolved.relative_to(root)}"
            ),
        }
    }
    return decision, f"allowed {resolved.relative_to(root)}"


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
