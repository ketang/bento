#!/usr/bin/env bash
# =============================================================================
# probe-stdout.sh — Evidence: what Claude interprets from hook stdout vs stderr
#
# CLAIM UNDER TEST
#   hook-environment.md states:
#     • stdout: only a hookSpecificOutput JSON object is interpreted; other
#       text is discarded (not shown to the model, not shown to the user)
#     • stderr: surfaced to the model as context when exit code is 2 (block);
#       for non-blocking exits (0), stderr is logged but not surfaced
#
# HOW TO RUN THE THREE EXPERIMENTS
#   Wire this script three times with the MODE env var set differently:
#
#   "PostToolUse": [
#     { "matcher": "Bash", "hooks": [
#         { "type": "command",
#           "command": "MODE=noise /path/to/probe-stdout.sh" },
#         { "type": "command",
#           "command": "MODE=json_allow /path/to/probe-stdout.sh" },
#         { "type": "command",
#           "command": "MODE=stderr_on_block /path/to/probe-stdout.sh" }
#     ]}
#   ]
#
#   Run each experiment separately; do not wire all three simultaneously or
#   the blocking mode will prevent the allow modes from being reached.
#
# EXPECTED RESULTS BY MODE
#
#   MODE=noise
#     stdout: "THIS TEXT SHOULD NOT APPEAR IN CLAUDE'S CONTEXT"
#     stderr: "stderr-noise: this is logged but not shown (exit 0)"
#     exit:   0
#     Expected: Claude proceeds normally; text on stdout is silently discarded.
#     If you see the stdout text appear in Claude's reply, the claim is wrong.
#
#   MODE=json_allow
#     stdout: { "hookSpecificOutput": { "permissionDecision": "allow", … } }
#     exit:   0
#     Expected: Claude auto-allows the Bash call without prompting.
#     The JSON is the structured channel; it is interpreted, not shown as text.
#
#   MODE=stderr_on_block
#     stderr: "BLOCK REASON: probe-stdout experiment — deliberately blocking"
#     exit:   2
#     Expected: Claude shows the stderr message as the denial reason.
#     If Claude does NOT show this message, the stderr-on-block claim is wrong.
# =============================================================================
set -euo pipefail

MODE="${MODE:-noise}"
PAYLOAD=$(cat)
OUTFILE="/tmp/hook-probe-stdout-${MODE}.txt"

log() { printf '%s\n' "$1" | tee -a "$OUTFILE"; }

> "$OUTFILE"
log "probe-stdout.sh MODE=$MODE  timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
log "Output file: $OUTFILE"
log ""

case "$MODE" in

  noise)
    log "EXPERIMENT: write non-JSON text to stdout (exit 0)"
    log "EXPECTATION: text below appears on stdout but Claude ignores it entirely"
    log "HOW TO VERIFY: watch Claude's next message — it should not contain the marker text"
    log ""
    # This goes to both the log file AND stdout.  Claude should discard the stdout copy.
    msg="THIS TEXT SHOULD NOT APPEAR IN CLAUDE'S CONTEXT [probe-stdout noise $(date +%s)]"
    log "Writing to stdout: $msg"
    printf '%s\n' "$msg"                          # <-- stdout: should be discarded
    printf 'stderr-noise: this is logged but not shown (exit 0)\n' >&2
    log ""
    log "RESULT: if Claude's reply does not mention the marker text, claim CONFIRMED."
    exit 0
    ;;

  json_allow)
    log "EXPERIMENT: emit hookSpecificOutput JSON to stdout (exit 0)"
    log "EXPECTATION: Claude interprets the JSON and auto-allows the Bash call"
    log "HOW TO VERIFY: the Bash call should proceed without a permission prompt"
    log ""
    TOOL_INPUT=$(printf '%s' "$PAYLOAD" \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('tool_input',{})))" \
      2>/dev/null || echo '{}')
    DECISION=$(python3 - "$TOOL_INPUT" <<'PYEOF'
import json, sys
tool_input = json.loads(sys.argv[1])
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "probe-stdout json_allow experiment",
        "updatedInput": tool_input
    }
}))
PYEOF
)
    log "Writing hookSpecificOutput JSON to stdout:"
    log "$DECISION"
    printf '%s\n' "$DECISION"                     # <-- stdout: should be interpreted
    log ""
    log "RESULT: if Bash ran without a permission prompt, JSON stdout claim CONFIRMED."
    exit 0
    ;;

  stderr_on_block)
    log "EXPERIMENT: write reason to stderr and exit 2 (block)"
    log "EXPECTATION: Claude surfaces the stderr message as the denial reason"
    log "HOW TO VERIFY: Claude's reply should quote or paraphrase the BLOCK REASON line"
    log ""
    REASON="BLOCK REASON: probe-stdout experiment — deliberately blocking to test stderr surfacing [$(date +%s)]"
    log "Writing to stderr: $REASON"
    printf '%s\n' "$REASON" >&2                   # <-- stderr: should be shown to model
    log ""
    log "RESULT: if Claude's reply references the BLOCK REASON text, claim CONFIRMED."
    exit 2
    ;;

  *)
    printf 'probe-stdout.sh: unknown MODE=%s\n' "$MODE" >&2
    exit 1
    ;;
esac
