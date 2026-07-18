#!/usr/bin/env bash
PAYLOAD=$(cat)
render() {
  echo "===== CODEX HOOK PROBE ====="
  echo "--- raw stdin payload ---"; echo "$PAYLOAD"
  echo "PWD=$PWD"; echo "HOME=$HOME"
  echo "CUSTOM_PROBE_VAR=${CUSTOM_PROBE_VAR:-<UNSET>}"
  echo "--- codex/agent injected vars ---"; env | grep -iE '^(CODEX|AI_AGENT|CLAUDECODE)' | sort
  echo "--- sample inherited user vars ---"; env | grep -iE '^(DOTFILES|NVM_DIR|SSH_AUTH_SOCK|TMUX)=' | sort
  echo "PATH=$PATH"
  [ -t 0 ] && echo "stdin: TTY" || echo "stdin: not a TTY"
  echo "login_shell: $(shopt -q login_shell && echo yes || echo no)"
  echo "===== END PROBE ====="
}
# try several writable roots
for dest in "$SP_OUT" "/tmp/codex-probe2.txt" "$HOME/.codex/tmp/codex-probe2.txt" "$PWD/.codex-probe-out.txt" "$CODEX_HOOK_OUT"; do
  [ -n "$dest" ] && render >> "$dest" 2>/dev/null
done
render 1>&2   # also to stderr
exit 0
