#!/usr/bin/env bash
# =============================================================================
# probe-env.sh — Evidence: hooks inherit the full parent-process environment
#
# CLAIM UNDER TEST
#   hooks/references/hook-environment.md states that hooks "do inherit the full
#   environment that Claude Code itself was launched with", including user-defined
#   variables, terminal variables, Claude-injected variables, and plugin PATH
#   entries.
#
# HOW TO WIRE (add to ~/.claude/settings.json under "hooks"):
#   "PostToolUse": [
#     { "matcher": "Bash",
#       "hooks": [{ "type": "command",
#                   "command": "/path/to/hooks/experiments/probe-env.sh" }] }
#   ]
#
# TRIGGER
#   Run any Bash tool call (e.g. `echo trigger`) in a new Claude session.
#
# OUTPUT
#   /tmp/hook-probe-env.txt  — full labelled report (persists after hook exits)
#   stderr                   — summary line visible in Claude's hook log
#
# WHAT THE OUTPUT PROVES
#   • User-defined variables (e.g. DOTFILES, GOPATH) are present  →  inherited
#   • Claude-injected variables (CLAUDECODE, CLAUDE_CODE_SESSION_ID) are present
#     →  Claude adds them before spawning subprocesses
#   • Plugin bin directories appear in PATH  →  Claude prepends them at startup
#   • NVM_DIR is set but nvm shim paths may be absent from PATH  →  env vars are
#     inherited as of Claude launch time; post-launch shell mutations are not
# =============================================================================
set -euo pipefail

OUTFILE="/tmp/hook-probe-env.txt"
STDIN_PAYLOAD=$(cat)

report() { printf '%s\n' "$1" | tee -a "$OUTFILE" >&2; }
section() { printf '\n=== %s ===\n' "$1" | tee -a "$OUTFILE" >&2; }
kv() { printf '  %-30s %s\n' "$1" "$2" | tee -a "$OUTFILE" >&2; }

# Start fresh
> "$OUTFILE"

report "probe-env.sh — hook environment variable evidence"
report "Run timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
report "Output file:   $OUTFILE"

# ------------------------------------------------------------------
section "1. PROCESS IDENTITY"
# ------------------------------------------------------------------
kv "PWD (working dir):"   "$PWD"
kv "USER:"                "${USER:-<unset>}"
kv "HOME:"                "${HOME:-<unset>}"
kv "SHELL:"               "${SHELL:-<unset>}"
kv "BASH_VERSION:"        "${BASH_VERSION:-<unset>}"

# ------------------------------------------------------------------
section "2. CLAUDE-INJECTED VARIABLES"
# Proves Claude adds these before spawning hook subprocesses.
# If these were absent, the claim that Claude injects them would be false.
# ------------------------------------------------------------------
for var in CLAUDECODE AI_AGENT CLAUDE_CODE_SESSION_ID CLAUDE_CODE_TMPDIR \
           CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_EXECPATH; do
  val="${!var:-<NOT SET — injection claim would be false>}"
  kv "$var:" "$val"
done

# ------------------------------------------------------------------
section "3. USER-DEFINED VARIABLES (inherited from parent process)"
# Proves hooks see variables the user set before launching Claude.
# DOTFILES is set in the user's shell config; if absent, inheritance is broken.
# ------------------------------------------------------------------
for var in DOTFILES GOPATH CARGO_HOME NVM_DIR HOMEBREW_PREFIX \
           HOMEBREW_CELLAR LOGDIR STORYBOOK_DISABLE_TELEMETRY; do
  val="${!var:-<not set in this environment>}"
  kv "$var:" "$val"
done

# ------------------------------------------------------------------
section "4. TERMINAL / SESSION VARIABLES"
# Proves hooks see tmux, SSH, and display variables from the parent session.
# These are only present if they were exported before Claude launched.
# ------------------------------------------------------------------
for var in TMUX TMUX_PANE TERM TERM_PROGRAM DISPLAY SSH_AUTH_SOCK \
           SSH_CLIENT SSH_CONNECTION; do
  val="${!var:-<not set>}"
  kv "$var:" "$val"
done

# ------------------------------------------------------------------
section "5. PATH ANALYSIS"
# Breaks PATH into entries so plugin bin dirs are visible individually.
# Claude prepends plugin cache bin dirs; user PATH entries follow.
# ------------------------------------------------------------------
plugin_entries=()
user_entries=()
IFS=: read -ra path_parts <<< "${PATH:-}"
for p in "${path_parts[@]}"; do
  if [[ "$p" == *"/.claude/plugins/"* ]]; then
    plugin_entries+=("$p")
  else
    user_entries+=("$p")
  fi
done

report ""
report "  Plugin-injected PATH entries (added by Claude at startup):"
if [[ ${#plugin_entries[@]} -eq 0 ]]; then
  report "    <none — plugin PATH injection claim would be false>"
else
  for p in "${plugin_entries[@]}"; do report "    $p"; done
fi

report ""
report "  User PATH entries (inherited from parent process):"
for p in "${user_entries[@]}"; do report "    $p"; done

# ------------------------------------------------------------------
section "6. WORKING DIRECTORY vs PAYLOAD cwd"
# Proves hooks run from \$HOME, not the project directory.
# The JSON payload carries the actual project cwd.
# ------------------------------------------------------------------
payload_cwd=$(printf '%s' "$STDIN_PAYLOAD" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('cwd','<no cwd in payload>'))" \
  2>/dev/null || echo "<could not parse payload>")

kv "Hook PWD (\$PWD):"       "$PWD"
kv "Payload cwd field:"      "$payload_cwd"
if [[ "$PWD" == "$HOME" ]]; then
  kv "VERDICT (cwd):"        "CONFIRMED — PWD is \$HOME, not project dir"
else
  kv "VERDICT (cwd):"        "UNEXPECTED — PWD is not \$HOME (was: $PWD)"
fi

# ------------------------------------------------------------------
section "7. TTY STATUS"
# Proves stdin/stdout/stderr are never TTYs inside a hook.
# ------------------------------------------------------------------
stdin_tty="no"
stdout_tty="no"
stderr_tty="no"
[ -t 0 ] && stdin_tty="YES — UNEXPECTED"
[ -t 1 ] && stdout_tty="YES — UNEXPECTED"
[ -t 2 ] && stderr_tty="YES — UNEXPECTED"
kv "stdin is TTY:"   "$stdin_tty"
kv "stdout is TTY:"  "$stdout_tty"
kv "stderr is TTY:"  "$stderr_tty"

# ------------------------------------------------------------------
section "8. STDIN PAYLOAD (truncated to 600 chars)"
# Documents the shape of the JSON Claude sends for PostToolUse/Bash.
# ------------------------------------------------------------------
short="${STDIN_PAYLOAD:0:600}"
report "$short"
[[ ${#STDIN_PAYLOAD} -gt 600 ]] && report "  ... (truncated; full payload is ${#STDIN_PAYLOAD} chars)"

# ------------------------------------------------------------------
section "9. PROCESS PARENT CHAIN"
# Shows what process spawned the hook, confirming the subprocess model.
# ------------------------------------------------------------------
pid=$$
for _i in $(seq 1 7); do
  ppid=$(awk '/^PPid:/{print $2}' "/proc/$pid/status" 2>/dev/null || echo "")
  name=$(cat "/proc/$pid/comm" 2>/dev/null || echo "?")
  cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | head -c 200)
  report "  PID $pid (ppid=${ppid:-?}) [$name]: $cmdline"
  [[ -z "$ppid" || "$ppid" == "0" ]] && break
  pid="$ppid"
done

# ------------------------------------------------------------------
section "SUMMARY"
# ------------------------------------------------------------------
report "Full report written to: $OUTFILE"
report "To read it: cat $OUTFILE"

exit 0
