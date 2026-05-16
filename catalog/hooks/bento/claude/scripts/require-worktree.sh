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

if ! repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  exit 0
fi

branch="$(git branch --show-current 2>/dev/null || true)"
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
exit 1
