#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
require-worktree: block Claude file edits directly on main.

Usage:
  require-worktree.sh
  require-worktree.sh -h|--help

Allows non-git directories, detached HEAD, non-main branches, and repos with
.agent-mode.local containing require_worktree=false.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

# Claude Code runs hook processes from $HOME, not the project root.
# Read the full stdin payload once; subsequent steps parse from this variable
# so stdin is not consumed twice.
payload_raw="$(cat 2>/dev/null || true)"

payload_cwd="$(echo "$payload_raw" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    v = d.get('cwd', '')
    if v:
        print(v)
except Exception:
    pass
" 2>/dev/null || true)"

check_dir="${payload_cwd:-$PWD}"

if ! repo_root="$(git -C "$check_dir" rev-parse --show-toplevel 2>/dev/null)"; then
  exit 0
fi

branch="$(git -C "$check_dir" branch --show-current 2>/dev/null || true)"
if [[ -z "$branch" || "$branch" != "main" ]]; then
  exit 0
fi

config_file="${repo_root}/.agent-mode.local"
if [[ -f "$config_file" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "$key" == "require_worktree" && "$value" == "false" ]]; then
      exit 0
    fi
  done < "$config_file"
fi

cat >&2 <<'MESSAGE'
Blocked: editing files directly on 'main' is not allowed.
To disable this check for this repo, add 'require_worktree=false' to .agent-mode.local.
MESSAGE

BENTO_PAYLOAD="$payload_raw" \
BENTO_REPO_ROOT="$repo_root" \
BENTO_BRANCH="$branch" \
python3 -c "
import datetime, json, os
from pathlib import Path

STRIP_KEYS = frozenset(['content', 'old_string', 'new_string', 'new_source', 'source'])

try:
    raw = os.environ.get('BENTO_PAYLOAD', '')
    d = json.loads(raw) if raw else {}
    tool_input = {k: v for k, v in d.get('tool_input', {}).items() if k not in STRIP_KEYS}
    record = {
        'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
        'session_id': d.get('session_id'),
        'tool_name': d.get('tool_name'),
        'cwd': d.get('cwd'),
        'repo_root': os.environ.get('BENTO_REPO_ROOT', ''),
        'branch': os.environ.get('BENTO_BRANCH', ''),
        'tool_input': tool_input,
    }
    date_str = datetime.date.today().isoformat()
    log_dir = Path.home() / '.claude' / 'hooks'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f'require-worktree-rejections.{date_str}.jsonl'
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record) + '\n')
except Exception:
    pass
" 2>/dev/null || true

# Exit code 2 is the documented PreToolUse blocking signal for both
# Claude Code and Codex; the reason message above (on stderr) is shown to
# the user. `exit 1` is classified as a non-blocking failure and the tool
# call proceeds, so the hook must use 2 (or a JSON deny decision on stdout)
# to actually block the edit.
exit 2
