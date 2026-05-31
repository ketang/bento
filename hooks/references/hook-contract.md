# Hook Contract

Canonical reference for the blocking and decision semantics of hooks in
`catalog/hooks/`. Read this before writing a new hook or modifying an existing
one. Examples in this repo:

- Claude `PreToolUse` permission decision: `catalog/hooks/bento/claude/scripts/auto-allow.py`
- Codex `PermissionRequest` decision: `catalog/hooks/bento/codex/scripts/permission-request.py`

Both runtimes evaluate two signals: the **process exit code** and an optional
**JSON decision** on stdout. Exit code is authoritative for blocking; the JSON
shape carries structured allow/deny semantics when the runtime supports it.

## Claude Code `PreToolUse`

### Exit codes

| Exit | Effect                                                                 |
| ---- | ---------------------------------------------------------------------- |
| `0`  | Allow. Tool call proceeds. JSON decision on stdout (if any) is honored. |
| `2`  | **Block.** Tool call is denied. Stderr is surfaced to the model as the reason. |
| other non-zero (`1`, `3`, ...) | **Non-blocking failure.** Logged as "Failed with non-blocking status code"; the tool call **proceeds**. |

`exit 1` is the most common mistake: it looks like "blocked" but the runtime
treats it as a soft failure and lets the tool run.

### JSON decision (stdout)

To deny structurally (instead of via exit `2`), emit on stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "why this was denied"
  }
}
```

`permissionDecision` accepts `"allow"`, `"deny"`, or `"ask"`. To allow, use the
same shape with `"allow"` — see `auto-allow.py` for a worked example.

A `"deny"` JSON decision blocks the tool call even when the exit code is `0`.
For hooks that need both a structured reason *and* the exit-code block path,
emit the JSON and exit `2`.

## Codex `PreToolUse` / `PermissionRequest`

Exit-code semantics match Claude Code: `0` = allow, `2` = block with stderr as
reason, other non-zero = non-blocking failure (tool proceeds).

Codex accepts two stdout JSON shapes for the decision:

**Modern shape** (matches Claude):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "why this was denied"
  }
}
```

**Legacy shape** (Codex-only):

```json
{"decision": "block", "reason": "why this was denied"}
```

New hooks should prefer the modern shape for portability across runtimes. The
legacy shape remains supported and is what older Codex examples use.

For `PermissionRequest` allow decisions, see
`catalog/hooks/bento/codex/scripts/permission-request.py`, which emits:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {"behavior": "allow"}
  }
}
```

## Worked examples

### Blocking hook (correct)

```bash
#!/usr/bin/env bash
# Block file edits on the main branch.
if [[ "$(git branch --show-current)" == "main" ]]; then
  echo "Blocked: do not edit files directly on main." >&2
  exit 2          # <-- exit 2 is what makes this a block
fi
exit 0
```

### Non-blocking hook (intentionally advisory)

```bash
#!/usr/bin/env bash
# Warn but allow the tool call.
if grep -q "TODO" "$1" 2>/dev/null; then
  echo "Note: file contains TODO markers." >&2
fi
exit 0            # exit 0 = allow; stderr is informational only
```

### Common mistake: silent failure that looks like a block

```bash
#!/usr/bin/env bash
# WRONG: exit 1 does NOT block on either runtime.
echo "Blocked: bad command." >&2
exit 1            # <-- treated as non-blocking failure; tool proceeds anyway
```

This pattern was the direct cause of `bento-fko`: a hook intended to block
edits on `main` exited `1` instead of `2`, so the runtime logged a non-blocking
failure and allowed the edit through. Any hook that means to block must exit
`2` (or emit a `"deny"` JSON decision).

## Authoring checklist

- Do you intend to block? Exit `2` (or emit `"permissionDecision": "deny"`).
  Never `exit 1`.
- Do you intend to allow but signal info? Exit `0` and write to stderr.
- Are you on Codex? Prefer the modern `hookSpecificOutput` shape; the legacy
  `{"decision": "block"}` shape is still accepted.
- Does the runtime call your hook with `cwd` in the stdin JSON payload? Read
  it from there, not from `$PWD` — Claude Code spawns hooks from `$HOME`.

## See Also

For working directory, environment variable inheritance, stdin shape, stdout
handling, TTY status, and common invalid assumptions, see
[`hook-environment.md`](hook-environment.md).
