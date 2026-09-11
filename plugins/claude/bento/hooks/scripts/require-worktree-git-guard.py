#!/usr/bin/env python3
"""PreToolUse/Bash hook: deny branch-mutating git and hook-bypassing git in
the primary checkout, so the "never mutate outside land-work" doctrine is
enforced mechanically instead of depending on the Bash permission allowlist
(which is friction control, not policy) (bento-rdtn.15).

Two independent rules, both advisory-free hard blocks (exit 2):

1. In the PRIMARY checkout only (never a linked worktree) -- `git merge`,
   `git rebase`, `git reset`, `git clean` in any form, `git checkout
   <primary-branch>`, `git branch -D <primary-branch>`, and `git push
   --force*` are denied. Opt out for a repo with `require_worktree=false` in
   `.agent-mode.local` (the same switch `require-worktree.sh` uses -- both
   enforce the same doctrine). A command containing the literal marker
   `BENTO_LAND_WORK=1` is treated as invoked by an authorized land-work/
   launch-work flow and skipped entirely: land.py (bento-rdtn.14) and the
   individual land-work-*.py scripts run their own git mutations as internal
   subprocess calls that never surface as a separate Bash tool call in the
   first place, so the marker exists only for the rare case of a raw git
   command that genuinely needs to run outside those scripts.
2. In any checkout -- `--no-verify` and a `-c core.hooksPath=...` (or
   `--config core.hooksPath=...`) override on a git invocation are denied.
   Opt out with `hook_bypass=allow` in `.agent-mode.local`.

This is a regex/token-level guard over the Bash command string, not a full
shell parser: it can be defeated by sufficiently obfuscated shell (command
substitution, sourced functions, etc.), matching the same trust model as
`require-worktree.sh`. It fails open (never blocks) on any git/parse error,
since the goal is to catch the common, unobfuscated case, not to be a
security boundary.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

LAND_WORK_MARKER = "BENTO_LAND_WORK=1"

_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;&|\n]")
_MUTATING_SUBCOMMANDS = frozenset({"merge", "rebase", "reset", "clean"})


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
        )
    except OSError:
        return None


def _repo_root(cwd: str) -> str | None:
    result = _git(["rev-parse", "--show-toplevel"], cwd)
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip()


def _is_primary_checkout(repo_root: str) -> bool:
    # A linked worktree's .git is a file (a "gitdir: ..." pointer); the
    # primary checkout's (or a bare repo's) .git is a directory.
    return (Path(repo_root) / ".git").is_dir()


def _detect_primary_branch(repo_root: str) -> str | None:
    origin_head = _git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], repo_root)
    if origin_head is not None and origin_head.returncode == 0 and origin_head.stdout.strip():
        return origin_head.stdout.strip().removeprefix("origin/")
    for candidate in ("main", "master"):
        for ref in (f"refs/heads/{candidate}", f"refs/remotes/origin/{candidate}"):
            check = _git(["show-ref", "--verify", ref], repo_root)
            if check is not None and check.returncode == 0:
                return candidate
    current = _git(["branch", "--show-current"], repo_root)
    if current is not None and current.returncode == 0 and current.stdout.strip():
        return current.stdout.strip()
    return None


def _read_agent_mode_keys(repo_root: str) -> dict[str, str]:
    config = Path(repo_root) / ".agent-mode.local"
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def _parse_git_invocation(tokens: list[str]) -> tuple[str | None, list[str], list[str]]:
    """From tokens after 'git', return (subcommand, remaining_args, config_values).

    config_values collects every `-c key=value` / `--config key=value`
    override seen before the subcommand, so a caller can check for
    `core.hooksPath` regardless of exactly how it was spelled.
    """
    i = 0
    configs: list[str] = []
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-c", "--config") and i + 1 < len(tokens):
            configs.append(tokens[i + 1])
            i += 2
            continue
        if tok.startswith("-c") and len(tok) > 2:
            configs.append(tok[2:])
            i += 1
            continue
        if tok in ("-C",) and i + 1 < len(tokens):
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= len(tokens):
        return None, [], configs
    return tokens[i], tokens[i + 1:], configs


def _find_git_segments(command: str) -> list[str]:
    """Each shell segment (split on ;, &&, ||, |, newline) that invokes git,
    with the 'git' token and anything before it in that segment stripped."""
    segments: list[str] = []
    for segment in _SEGMENT_SPLIT_RE.split(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        # Skip leading VAR=value env-assignment tokens.
        idx = 0
        while idx < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[idx]):
            idx += 1
        if idx < len(tokens) and tokens[idx] == "git":
            segments.append(tokens[idx + 1:])
    return segments


def _hook_bypass_reason(git_tokens: list[str]) -> str | None:
    if "--no-verify" in git_tokens:
        return "'--no-verify' skips git hooks"
    _subcommand, _rest, configs = _parse_git_invocation(git_tokens)
    for value in configs:
        if value.split("=", 1)[0].strip() == "core.hooksPath":
            return f"'-c {value}' overrides core.hooksPath, skipping git hooks"
    return None


def _mutation_reason(git_tokens: list[str], primary_branch: str | None) -> str | None:
    subcommand, rest, _configs = _parse_git_invocation(git_tokens)
    if subcommand is None:
        return None
    if subcommand in _MUTATING_SUBCOMMANDS:
        return f"'git {subcommand}' mutates the checkout"
    if subcommand == "checkout" and primary_branch and primary_branch in rest:
        return f"'git checkout {primary_branch}' switches the primary checkout's own branch"
    if subcommand == "branch" and primary_branch and primary_branch in rest and (
        "-D" in rest or "--delete" in rest or "-d" in rest
    ):
        return f"'git branch -D {primary_branch}' deletes the primary branch"
    if subcommand == "push" and any(arg == "--force" or arg == "-f" or arg.startswith("--force") for arg in rest):
        return "'git push --force*' force-pushes"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return 0
    cwd = payload.get("cwd") or ""

    try:
        if LAND_WORK_MARKER in command:
            return 0

        repo_root = _repo_root(cwd) if cwd else None
        if repo_root is None:
            return 0

        agent_mode = _read_agent_mode_keys(repo_root)
        is_primary = _is_primary_checkout(repo_root)
        primary_branch = _detect_primary_branch(repo_root) if is_primary else None

        for git_tokens in _find_git_segments(command):
            bypass_reason = _hook_bypass_reason(git_tokens)
            if bypass_reason and agent_mode.get("hook_bypass") != "allow":
                print(
                    f"Blocked: {bypass_reason}.\n"
                    "Hook timeouts should be fixed at the source, not bypassed -- see "
                    "the launch-work skill's dependency-bootstrap guidance for slow-hook "
                    "fixes. To disable this check for this repo, add 'hook_bypass=allow' "
                    "to .agent-mode.local.",
                    file=sys.stderr,
                )
                return 2

            if is_primary and agent_mode.get("require_worktree") != "false":
                mutation_reason = _mutation_reason(git_tokens, primary_branch)
                if mutation_reason:
                    print(
                        f"Blocked: {mutation_reason} in the primary checkout, which is not "
                        "allowed outside the land-work/launch-work flow.\n"
                        "Land and merge from a linked worktree via the land-work skill "
                        "(land-work/scripts/land.py) instead of mutating the primary "
                        "checkout directly. To disable this check for this repo, add "
                        "'require_worktree=false' to .agent-mode.local.",
                        file=sys.stderr,
                    )
                    return 2
    except Exception:
        # Never block the session on an unexpected error in this guard.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
