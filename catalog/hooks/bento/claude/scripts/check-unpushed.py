#!/usr/bin/env python3
"""Stop hook: block ending a session with uncommitted or unpushed work.

Blocks (exit 2) when the session cwd's git repo has a dirty working tree
(``git status --porcelain`` non-empty) or has local commits ahead of its
upstream (``git rev-list @{u}..HEAD --count`` > 0). The exception is the two
Beads operational projections that normal tracker synchronization updates:
``.beads/backup/backup_state.json`` and ``.beads/interactions.jsonl``. They
do not represent unlanded repository work on their own. The blocking reason on
stderr names the branch and the counts so it is actionable.

A branch with no upstream is treated as a warning, not a block: worktree flows
that have not pushed a first commit yet must not be trapped, so a clean
no-upstream branch passes. A dirty tree still blocks regardless of upstream.

Silent no-op cases (exit 0): no/invalid cwd, a non-git cwd, a repo that opts
out via ``require_pushed=false`` in ``.agent-mode.local``, re-entrant Stop
invocations (``stop_hook_active``) so a block never loops forever, a
land-work merge-preview worktree (its staged changes are the merge candidate
being verified, not stranded work), and a worktree with an in-progress
rebase/merge/cherry-pick (its detached HEAD and staged files are normal
mid-operation state, not abandoned work).

Claude Code runs hook processes from $HOME, not the project root, so the
session directory is read from the stdin JSON payload's ``cwd`` field, never
from $PWD or the process CWD.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


OPERATIONAL_BEADS_PATHS = frozenset(
    {
        ".beads/backup/backup_state.json",
        ".beads/interactions.jsonl",
    }
)


def _git(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", root, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def repo_root(cwd: str) -> str | None:
    result = _git(cwd, "rev-parse", "--show-toplevel")
    root = result.stdout.strip()
    return root if result.returncode == 0 and root else None


def is_suppressed(root: str) -> bool:
    """True when .agent-mode.local sets require_pushed=false."""
    config = Path(root) / ".agent-mode.local"
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key.strip() == "require_pushed" and value.strip() == "false":
            return True
    return False


def current_branch(root: str) -> str:
    return _git(root, "branch", "--show-current").stdout.strip()


def is_registered_worktree(root: str) -> bool:
    """True when root is a live entry in its repo's ``git worktree list``.

    A worktree that a failed/interrupted land-work landing leaked (bento-gd2)
    and a manual sweep has not yet removed is still registered; one that has
    since been pruned or replaced is not.
    """
    result = _git(root, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return False
    root_resolved = str(Path(root).resolve())
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
            if str(Path(path).resolve()) == root_resolved:
                return True
    return False


def is_land_work_preview(root: str) -> bool:
    """True when root is a live, still-detached land-work merge-preview worktree.

    ``land-work-create-preview.py`` materializes previews via
    ``tempfile.mkdtemp(prefix="land-work-preview-", dir="/tmp")`` and
    ``git worktree add --detach``. The name prefix alone is not sufficient:
    a leaked preview directory (bento-gd2) could be reused later for real,
    attached-branch work before a closure sweep removes it, so this also
    requires HEAD to still be detached and the path to still be a registered
    worktree before treating it as a live preview.
    """
    if not Path(root).name.startswith("land-work-preview-"):
        return False
    if current_branch(root):
        return False
    return is_registered_worktree(root)


def _resolves_to_commit(root: str, ref_or_sha: str) -> bool:
    if not ref_or_sha:
        return False
    result = _git(root, "cat-file", "-e", f"{ref_or_sha}^{{commit}}")
    return result.returncode == 0


def _is_ancestor_of_head(root: str, sha: str) -> bool:
    result = _git(root, "merge-base", "--is-ancestor", sha, "HEAD")
    return result.returncode == 0


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_incoming_merge_parent(root: str, sha: str) -> bool:
    """True when sha resolves to a real commit that is not already reachable
    from HEAD.

    A real incoming merge/cherry-pick parent is never already an ancestor of
    (or equal to) HEAD. A faked marker such as ``git rev-parse HEAD >
    .git/MERGE_HEAD`` resolves to a real commit but is HEAD's own ancestor,
    so this closes that bypass without needing reflog archaeology.
    """
    return _resolves_to_commit(root, sha) and not _is_ancestor_of_head(root, sha)


def has_in_progress_operation(root: str) -> bool:
    """True when root's worktree has a rebase, merge, or cherry-pick underway.

    Marker *existence* alone is gameable: a bare ``touch .git/MERGE_HEAD`` or
    ``mkdir .git/rebase-merge`` would otherwise bypass the whole check. Each
    marker is only trusted once it correlates with real git state that a
    trivial fake file cannot reproduce.

    MERGE_HEAD/CHERRY_PICK_HEAD hold one SHA per line (an octopus merge lists
    one per non-first parent) — every non-empty line must resolve to a real
    commit that is not already an ancestor of HEAD. A rebase directory must
    both carry the ``onto`` file a real ``git rebase`` always writes (also
    resolving to a real commit) and have detached HEAD, since a real rebase
    always detaches HEAD to replay commits.
    """
    result = _git(root, "rev-parse", "--git-dir")
    if result.returncode != 0:
        return False
    git_dir_raw = result.stdout.strip()
    if not git_dir_raw:
        return False
    git_dir = Path(git_dir_raw)
    if not git_dir.is_absolute():
        git_dir = Path(root) / git_dir

    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD"):
        marker_path = git_dir / marker
        if not marker_path.exists():
            continue
        shas = [line.strip() for line in _read_text(marker_path).splitlines() if line.strip()]
        if shas and all(_is_incoming_merge_parent(root, sha) for sha in shas):
            return True

    for rebase_dir in ("rebase-merge", "rebase-apply"):
        rebase_path = git_dir / rebase_dir
        if not rebase_path.is_dir():
            continue
        onto = _read_text(rebase_path / "onto").strip()
        if onto and _resolves_to_commit(root, onto) and not current_branch(root):
            return True

    return False


def is_dirty(root: str) -> bool:
    result = _git(root, "status", "--porcelain")
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def has_only_operational_beads_changes(root: str) -> bool:
    """Whether every dirty record is a tracked Beads operational projection.

    Porcelain v1 with ``-z`` puts a rename or copy destination in the first
    record and its source in the next one. Both paths must be allowlisted.
    Untracked changes and an unparseable status fail closed.
    """
    result = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode != 0 or not result.stdout:
        return False

    records = result.stdout.split("\0")
    index = 0
    saw_change = False
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            return False
        status, path = record[:2], record[3:]
        if status == "??" or path not in OPERATIONAL_BEADS_PATHS:
            return False
        saw_change = True
        if "R" in status or "C" in status:
            if index >= len(records):
                return False
            source_path = records[index]
            index += 1
            if not source_path or source_path not in OPERATIONAL_BEADS_PATHS:
                return False
    return saw_change


def has_upstream(root: str) -> bool:
    result = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return result.returncode == 0


def ahead_count(root: str) -> int:
    result = _git(root, "rev-list", "@{u}..HEAD", "--count")
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def has_only_operational_beads_commits(root: str) -> bool:
    """Whether every commit ahead of upstream changes only Beads projections.

    ``-m`` compares a merge against every parent, so a source change hidden by
    one parent still keeps the Stop hook blocking. Any Git failure fails closed.
    """
    commits = _git(root, "rev-list", "@{u}..HEAD")
    if commits.returncode != 0:
        return False
    commit_ids = [commit for commit in commits.stdout.splitlines() if commit]
    if not commit_ids:
        return False
    for commit_id in commit_ids:
        changes = _git(
            root,
            "diff-tree",
            "--no-commit-id",
            "-r",
            "-m",
            "--root",
            "--name-only",
            "-z",
            commit_id,
        )
        if changes.returncode != 0:
            return False
        paths = [path for path in changes.stdout.split("\0") if path]
        if not paths or any(path not in OPERATIONAL_BEADS_PATHS for path in paths):
            return False
    return True


def block_reason(hook_input: dict) -> str | None:
    """Return a blocking stderr message, or None to allow the stop."""
    if hook_input.get("stop_hook_active"):
        return None

    cwd = hook_input.get("cwd") or ""
    if not cwd or not os.path.isdir(cwd):
        return None

    root = repo_root(cwd)
    if root is None:
        return None

    if is_suppressed(root):
        return None

    if is_land_work_preview(root):
        return None

    if has_in_progress_operation(root):
        return None

    problems: list[str] = []
    if is_dirty(root) and not has_only_operational_beads_changes(root):
        problems.append("uncommitted changes")

    # A missing upstream is a warning, not a block, so worktree flows that have
    # not pushed a first commit are not trapped. Only count ahead commits when
    # an upstream exists.
    if has_upstream(root):
        ahead = ahead_count(root)
        if ahead > 0 and not has_only_operational_beads_commits(root):
            noun = "commit" if ahead == 1 else "commits"
            problems.append(f"{ahead} unpushed {noun}")

    if not problems:
        return None

    branch = current_branch(root) or "(detached HEAD)"
    joined = " and ".join(problems)
    return (
        f"Session end blocked: branch '{branch}' has {joined}.\n"
        "Commit and push your work before ending the session. "
        "To suppress this check for this repo, add 'require_pushed=false' to "
        ".agent-mode.local.\n"
    )


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        # Never break session stop on a malformed payload.
        return 0
    try:
        reason = block_reason(hook_input)
    except Exception:
        # Never break session stop on an unexpected git/filesystem error.
        return 0
    if reason:
        # Exit code 2 is the documented Stop blocking signal for Claude Code:
        # the stderr message is fed back to the model. Exit 1 is a non-blocking
        # failure and lets the stop proceed, so the hook must use 2 to block.
        sys.stderr.write(reason)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
