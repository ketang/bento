#!/usr/bin/env bash
# =============================================================================
# probe-stdin.sh — Evidence: hook stdin shape per event type
#
# CLAIM UNDER TEST
#   hook-environment.md states that hooks receive a JSON payload on stdin whose
#   fields vary by event type.  This script captures and pretty-prints the exact
#   payload so the claim can be verified against real Claude output.
#
# SUGGESTED WIRING (test multiple event types by adding to each):
#
#   "PreToolUse": [
#     { "matcher": "Bash",
#       "hooks": [{ "type": "command",
#                   "command": "PROBE_EVENT=PreToolUse_Bash /path/to/probe-stdin.sh" }] },
#     { "matcher": "Edit",
#       "hooks": [{ "type": "command",
#                   "command": "PROBE_EVENT=PreToolUse_Edit /path/to/probe-stdin.sh" }] }
#   ],
#   "PostToolUse": [
#     { "matcher": "Bash",
#       "hooks": [{ "type": "command",
#                   "command": "PROBE_EVENT=PostToolUse_Bash /path/to/probe-stdin.sh" }] }
#   ],
#   "SessionStart": [
#     { "matcher": "",
#       "hooks": [{ "type": "command",
#                   "command": "PROBE_EVENT=SessionStart /path/to/probe-stdin.sh" }] }
#   ],
#   "Stop": [
#     { "matcher": "",
#       "hooks": [{ "type": "command",
#                   "command": "PROBE_EVENT=Stop /path/to/probe-stdin.sh" }] }
#   ]
#
# TRIGGER
#   Start a new Claude session (SessionStart), run a Bash command (PreToolUse,
#   PostToolUse), edit a file (PreToolUse Edit), or end the session (Stop).
#
# OUTPUT
#   /tmp/hook-probe-stdin-<EVENT>.txt for each event type observed.
#   Each file contains the pretty-printed JSON payload with field annotations.
# =============================================================================
set -euo pipefail

EVENT="${PROBE_EVENT:-unknown}"
OUTFILE="/tmp/hook-probe-stdin-${EVENT}.txt"
PAYLOAD=$(cat)

annotate() {
  python3 - "$1" "$2" <<'PYEOF'
import json, sys

raw = sys.argv[1]
event = sys.argv[2]

try:
    d = json.loads(raw)
except Exception as e:
    print(f"  <could not parse JSON: {e}>")
    print(f"  Raw (first 500 chars): {raw[:500]}")
    sys.exit(0)

FIELD_NOTES = {
    "session_id":        "UUID — same across all hooks in one Claude session",
    "tool_name":         "Which Claude tool fired (Bash, Edit, Write, …)",
    "tool_input":        "The arguments Claude passed to the tool",
    "tool_response":     "PostToolUse only — the tool's return value",
    "cwd":               "Project directory at time of tool call (NOT the hook's PWD)",
    "transcript_path":   "Path to the session's JSONL transcript on disk",
    "stop_hook_active":  "Stop only — true if a Stop hook is already running",
    "prompt":            "UserPromptSubmit only — the text the user submitted",
    "agent_type":        "Subagent type if running inside a spawned agent",
    "hook_event_name":   "Mirrors the hook event name",
}

print(f"\n  Event type: {event}")
print(f"  Top-level keys present: {list(d.keys())}\n")
for k, v in d.items():
    note = FIELD_NOTES.get(k, "")
    display = json.dumps(v) if not isinstance(v, str) else repr(v)
    if len(display) > 120:
        display = display[:117] + "…"
    note_str = f"  ← {note}" if note else ""
    print(f"  {k!r:30s} = {display}{note_str}")
PYEOF
}

{
  printf 'probe-stdin.sh — stdin payload for event: %s\n' "$EVENT"
  printf 'Run timestamp: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf 'Output file:   %s\n\n' "$OUTFILE"
  annotate "$PAYLOAD" "$EVENT"
  printf '\n--- raw payload (complete) ---\n'
  printf '%s\n' "$PAYLOAD" | python3 -m json.tool 2>/dev/null || printf '%s\n' "$PAYLOAD"
} | tee "$OUTFILE" >&2

exit 0
