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
   Each git segment is judged against its *effective* repo: the payload cwd
   advanced by preceding literal `cd <path>` segments, then each `-C <path>`
   in order (non-literal paths, and paths that are not a repo, fall back to
   the running directory).
   In ANY checkout, a `git push` whose destination is the primary branch
   (`<src>:main`, `refs/heads/main`, or a bare push while on it) is denied.
2. In any checkout -- `--no-verify` and a `-c core.hooksPath=...` (or
   `--config core.hooksPath=...`) override on a git invocation are denied.
   Opt out with `hook_bypass=allow` in `.agent-mode.local`.

This guard parses the Bash command string with `shell_segments` (a sibling,
character-level shell segmenter -- see that module's docstring), not a full
shell parser: it can still be defeated by sufficiently obfuscated shell (the
body of `bash -c`/`eval`, sourced functions, etc.), matching the same trust
model as `require-worktree.sh`. It fails open (never blocks) on any git/parse
error, since the goal is to catch the common, unobfuscated case -- including
`git` behind a `rtk`/`command`/`env` wrapper -- not to be a security
boundary. It does not, by design, match text inside quoted strings or
heredoc bodies that merely *mentions* a git command (bento-l01v).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shell_segments import SegmentError, command_segments  # noqa: E402

LAND_WORK_MARKER = "BENTO_LAND_WORK=1"

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


def _parse_git_invocation(
    tokens: list[str],
) -> tuple[str | None, list[str], list[str], list[str]]:
    """From tokens after 'git', return (subcommand, remaining_args,
    config_values, dash_c_paths).

    dash_c_paths collects every `-C <path>` in order (git composes them).

    config_values collects every `-c key=value` / `--config key=value`
    override seen before the subcommand, so a caller can check for
    `core.hooksPath` regardless of exactly how it was spelled.
    """
    i = 0
    configs: list[str] = []
    dash_c: list[str] = []
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
            dash_c.append(tokens[i + 1])
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= len(tokens):
        return None, [], configs, dash_c
    return tokens[i], tokens[i + 1:], configs, dash_c


def _is_literal_path(path: str) -> bool:
    return not any(ch in path for ch in "$`*?[") and not (
        path.startswith("~") and path not in ("~",) and not path.startswith("~/")
    )


def _resolve_dir(base: str, path: str) -> str | None:
    """`path` applied to `base` as cd/-C would, or None when `path` is not a
    literal we can resolve (variables, substitutions, ~user)."""
    if not path or not _is_literal_path(path):
        return None
    return os.path.normpath(os.path.join(base, os.path.expanduser(path)))


def _find_git_segments(command: str, cwd: str) -> list[tuple[str, list[str]]]:
    """Each simple command in `command` that invokes git (directly, or via
    a stripped `rtk`/`exec`/`command`/`env` wrapper prefix -- see
    shell_segments.strip_wrapper_prefix), as (running_dir, tokens) with the
    'git' token itself removed. running_dir is the payload cwd advanced by
    every preceding literal `cd <path>` segment (a non-literal or bare `cd`
    leaves it unchanged). Raises no exception: a SegmentError from the
    scanner means "cannot fully parse this command" and is treated the same
    as "no git segments found" (fail open) by the caller.

    Subshell bodies are flattened in source order, so `(cd x && ...); git ...`
    over-applies the cd; the cwd fallback is the only defense there.
    """
    try:
        segments = command_segments(command)
    except SegmentError:
        return []
    running = cwd
    found: list[tuple[str, list[str]]] = []
    for segment in segments:
        if not segment:
            continue
        if segment[0] == "cd" and len(segment) == 2 and cwd:
            resolved = _resolve_dir(running, segment[1])
            if resolved is not None:
                running = resolved
        elif segment[0] == "git":
            found.append((running, segment[1:]))
    return found


def _hook_bypass_reason(git_tokens: list[str]) -> str | None:
    subcommand, rest, configs, _dash_c = _parse_git_invocation(git_tokens)
    if "--no-verify" in git_tokens:
        return "'--no-verify' skips git hooks"
    # '-n' is the documented short alias for --no-verify, but only for
    # 'commit' -- git overloads -n for other meanings elsewhere (e.g. 'git
    # log -n 5', 'git branch -n'), so this must not fire for those.
    if subcommand == "commit" and "-n" in rest:
        return "'-n' (short for --no-verify) skips git hooks"
    for value in configs:
        if value.split("=", 1)[0].strip() == "core.hooksPath":
            return f"'-c {value}' overrides core.hooksPath, skipping git hooks"
    return None


_PUSH_VALUE_OPTS = frozenset({"--repo", "-o", "--push-option", "--receive-pack", "--exec"})


def _push_destinations(rest: list[str]) -> tuple[list[str], bool]:
    """(destination branch names, has_explicit_refspec) for `git push` args.

    The first positional is the remote; later ones are refspecs. A refspec's
    destination is the part after ':' (else the source itself), minus a
    leading '+' and 'refs/heads/'.
    """
    positional: list[str] = []
    skip = False
    for arg in rest:
        if skip:
            skip = False
        elif arg in _PUSH_VALUE_OPTS:
            skip = True
        elif not arg.startswith("-"):
            positional.append(arg)
    dests: list[str] = []
    for spec in positional[1:]:
        dst = spec.removeprefix("+").rpartition(":")[2]
        dests.append(dst.removeprefix("refs/heads/"))
    return dests, len(positional) > 1


def _push_to_primary_reason(
    git_tokens: list[str], primary_branch: str | None, current_branch: str | None,
) -> str | None:
    subcommand, rest, _configs, _dash_c = _parse_git_invocation(git_tokens)
    if subcommand != "push" or not primary_branch:
        return None
    dests, explicit = _push_destinations(rest)
    # 'HEAD' as a destination (or bare source) means the current branch.
    dests = [current_branch if d == "HEAD" else d for d in dests]
    if primary_branch in dests:
        return f"'git push' updates the primary branch '{primary_branch}'"
    if not explicit and "--tags" not in rest and current_branch == primary_branch:
        return f"'git push' from the primary branch '{primary_branch}' updates it"
    return None


def _mutation_reason(git_tokens: list[str], primary_branch: str | None) -> str | None:
    subcommand, rest, _configs, _dash_c = _parse_git_invocation(git_tokens)
    if subcommand is None:
        return None
    if subcommand in _MUTATING_SUBCOMMANDS:
        return f"'git {subcommand}' mutates the checkout"
    if subcommand == "checkout" and primary_branch:
        # 'git checkout [<tree-ish>] -- <pathspec>...' restores files from a
        # ref (or the index); it does not switch the current branch. The
        # presence of '--' anywhere marks this form, regardless of whether
        # the ref name appears before it -- 'git checkout main -- file.txt'
        # uses "main" as the source tree-ish, not as a branch to switch to.
        if "--" not in rest and primary_branch in rest:
            return f"'git checkout {primary_branch}' switches the primary checkout's own branch"
    if subcommand == "branch" and primary_branch and primary_branch in rest and (
        "-D" in rest or "--delete" in rest or "-d" in rest
    ):
        return f"'git branch -D {primary_branch}' deletes the primary branch"
    if subcommand == "push" and any(
        arg == "--force" or arg == "-f" or arg.startswith("--force") or arg.startswith("+")
        for arg in rest
    ):
        return "'git push --force*' (or a leading '+' force-push refspec) force-pushes"
    return None


class _RepoInfo:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root
        self.agent_mode = _read_agent_mode_keys(repo_root)
        self.is_primary = _is_primary_checkout(repo_root)
        self.primary_branch = _detect_primary_branch(repo_root)
        current = _git(["branch", "--show-current"], repo_root)
        self.current_branch = (
            current.stdout.strip() if current is not None and current.returncode == 0 else None
        )


def _effective_dir(running: str, dash_c: list[str]) -> str:
    """Directory git operates in: `running` with each -C applied in order. A
    non-literal -C is skipped (fail toward the cwd-based decision)."""
    directory = running
    for path in dash_c:
        resolved = _resolve_dir(directory, path)
        if resolved is not None:
            directory = resolved
    return directory


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

        # Cheap, git-free check first: most Bash calls in a repo aren't git
        # invocations at all, and every git call below costs a subprocess --
        # skip all of them (repo-root resolution included) unless this
        # command actually contains one.
        git_segments = _find_git_segments(command, cwd)
        if not git_segments:
            return 0

        if not cwd or _repo_root(cwd) is None:
            return 0

        infos: dict[str, _RepoInfo | None] = {}

        def info_for(directory: str) -> _RepoInfo | None:
            if directory not in infos:
                root = _repo_root(directory) if os.path.isdir(directory) else None
                infos[directory] = _RepoInfo(root) if root else None
            return infos[directory]

        for running, git_tokens in git_segments:
            _sub, _rest, _cfg, dash_c = _parse_git_invocation(git_tokens)
            # An unresolvable target (missing dir, not a repo) falls back to
            # the running directory -- never toward allowing.
            info = info_for(_effective_dir(running, dash_c)) or info_for(running) or info_for(cwd)
            if info is None:
                continue
            agent_mode = info.agent_mode

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

            if agent_mode.get("require_worktree") == "false":
                continue

            mutation_reason = (
                _mutation_reason(git_tokens, info.primary_branch) if info.is_primary else None
            )
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

            push_reason = _push_to_primary_reason(
                git_tokens, info.primary_branch, info.current_branch,
            )
            if push_reason:
                print(
                    f"Blocked: {push_reason}, which is not allowed outside the "
                    "land-work flow.\n"
                    "Push your feature branch and land via the land-work skill "
                    "(land-work/scripts/land.py). To disable this check for this "
                    "repo, add 'require_worktree=false' to .agent-mode.local.",
                    file=sys.stderr,
                )
                return 2
    except Exception:
        # Never block the session on an unexpected error in this guard.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
