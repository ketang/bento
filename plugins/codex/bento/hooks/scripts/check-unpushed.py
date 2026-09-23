#!/usr/bin/env python3
"""Stop hook: block ending a session with uncommitted or unpushed work.

Blocks (exit 2) when the session cwd's git repo has a dirty working tree
(``git status --porcelain`` non-empty) or has local commits ahead of its
upstream (``git rev-list @{u}..HEAD --count`` > 0). The exception is any path
matching a glob pattern listed in the ``check-unpushed/dirty-state-exempt-
paths.txt`` customization file, resolved via the agent-plugins convention
(marketplace ``bento``, plugin ``bento``): repo scope
(``.agent-plugins/bento/bento/check-unpushed/dirty-state-exempt-paths.txt``)
overrides home scope, which overrides this hook's bundled default (shipped
alongside this script as ``dirty-state-exempt-paths.default.txt``, currently
listing Beads' two operational projections,
``.beads/backup/backup_state.json`` and ``.beads/interactions.jsonl``). This
hook itself stays tracker-agnostic -- it does not hardcode any tracker's file
layout in code; a tracker plugin registers its own operational-noise files by
shipping or overriding that customization file instead. Paths matching none
of the resolved patterns still block; with no file resolved, nothing is
exempt. The blocking reason on stderr names the branch and the counts so it
is actionable.

A branch with no upstream is treated as a warning, not a block: worktree flows
that have not pushed a first commit yet must not be trapped, so a clean
no-upstream branch passes. A dirty tree still blocks regardless of upstream.

Silent no-op cases (exit 0): no/invalid cwd, a non-git cwd, a repo that opts
out via ``require_pushed=false`` in ``.agent-mode.local``, re-entrant Stop
invocations (``stop_hook_active``) so a block never loops forever, a
land-work merge-preview worktree (its staged changes are the merge candidate
being verified, not stranded work), a repo's configured
``landing.integration_worktree`` (bento-96ua.1 — it never accumulates real
work of its own; every commit or staged change inside it is fully
reproducible by re-running the merge preview from the base and feature
branches), and a worktree with an in-progress rebase/merge/cherry-pick (its
detached HEAD and staged files are normal mid-operation state, not abandoned
work).

A block that repeats with the exact same problem kinds (still dirty, still
unpushed) within the same session is condensed to a one-line reminder instead
of re-emitting the full explanatory text every turn (bento-neng) -- Stop fires
at the end of every turn, so a long unpushed work session would otherwise see
the identical full message dozens of times in a row. The full message returns
whenever the problem kinds change (e.g. a clean-but-unpushed branch goes
dirty) or in a fresh session. This never changes whether the hook blocks --
exit 2 fires every time there is a real problem, regardless of whether the
message is full or condensed; only the verbosity is throttled, using the same
session-scoped runtime-dir marker mechanism as the advisory throttle below.
Without a session_id there is nowhere safe to persist "already shown," so the
full message is always shown in that case.

When none of the above apply and the branch is clean and fully pushed (the
case that otherwise passes in total silence), a second, non-blocking check
(bento-rdtn.11) looks for a branch that is pushed but never landed: not the
primary branch, has an upstream with zero unpushed commits, and is not yet
an ancestor of origin/<primary>. That prints one advisory line to stderr and
still exits 0 — it never blocks. Suppressed by ``require_landed=false`` in
``.agent-mode.local`` (independent of ``require_pushed``), and by every
worktree-kind exemption above. Never fires on the primary branch or a
detached HEAD. Throttled to once per Claude/Codex session per (repo, branch)
pair via a small marker file under ``$XDG_RUNTIME_DIR`` (or ``/tmp`` when
unset), keyed on the hook payload's ``session_id`` — Stop fires at the end
of every turn, not only at session exit, so an unthrottled advisory would
repeat identically after every subsequent turn in the same session.

Claude Code runs hook processes from $HOME, not the project root, so the
session directory is read from the stdin JSON payload's ``cwd`` field, never
from $PWD or the process CWD.
"""

import fcntl
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


TURN_HOLD_PREFIX = "bento-check-unpushed-hold-"


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


def _agent_mode_value(root: str, key: str) -> str | None:
    """The value of ``<key>=...`` in .agent-mode.local, or None if unset.

    A later line for the same key wins, matching normal config-file
    expectations. Absent file or key is not an error.
    """
    config = Path(root) / ".agent-mode.local"
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    value = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line_key, _, line_value = line.partition("=")
        if line_key.strip() == key:
            value = line_value.strip()
    return value


def _agent_mode_flag_is_false(root: str, flag: str) -> bool:
    """True when .agent-mode.local sets ``<flag>=false``."""
    return _agent_mode_value(root, flag) == "false"


def is_suppressed(root: str) -> bool:
    """True when .agent-mode.local sets require_pushed=false."""
    return _agent_mode_flag_is_false(root, "require_pushed")


_EXEMPT_PATHS_REL_PATH = "check-unpushed/dirty-state-exempt-paths.txt"
_BUNDLED_DEFAULT_EXEMPT_PATHS_FILE = SCRIPT_DIR / "dirty-state-exempt-paths.default.txt"


def _launch_work_scripts_dir() -> Path | None:
    """Locate launch-work/scripts/ (home of agent_plugins_resolver.py)
    relative to this hook's own location.

    Catalog and generated-plugin trees nest hooks/ and skills/ at different
    relative depths (``catalog/hooks/bento/<agent>/scripts/`` vs
    ``plugins/<agent>/bento/hooks/scripts/``), so try both candidate depths,
    mirroring ``_swarm_discover_script`` below.
    """
    candidates = (
        SCRIPT_DIR.parents[3] / "skills" / "launch-work" / "scripts",
        SCRIPT_DIR.parents[1] / "skills" / "launch-work" / "scripts",
    )
    for candidate in candidates:
        if (candidate / "agent_plugins_resolver.py").is_file():
            return candidate
    return None


def _agent_plugins_resolver():
    """Import agent_plugins_resolver.py, or None when it cannot be found.

    Imported lazily (rather than at module load) so a repo without the
    launch-work skill installed still runs this hook with no exemptions,
    instead of failing to import at all.
    """
    scripts_dir = _launch_work_scripts_dir()
    if scripts_dir is None:
        return None
    path_str = str(scripts_dir)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    try:
        import agent_plugins_resolver  # type: ignore
    except ImportError:
        return None
    return agent_plugins_resolver


def dirty_state_exempt_patterns(root: str) -> tuple[str, ...]:
    """Repo-relative glob patterns exempted from the dirty/unpushed block.

    Resolved via the agent-plugins convention (marketplace "bento", plugin
    "bento", file "check-unpushed/dirty-state-exempt-paths.txt"): repo scope
    overrides home scope, which overrides this hook's own bundled default.
    This is the generic extension point any tracker plugin uses to register
    its own operational-noise files instead of this tracker-agnostic hygiene
    hook hardcoding one tracker's file layout in code. One glob pattern per
    line; blank lines and ``#`` comments are ignored.
    """
    resolver = _agent_plugins_resolver()
    if resolver is None:
        return ()
    bundled_default = (
        _BUNDLED_DEFAULT_EXEMPT_PATHS_FILE
        if _BUNDLED_DEFAULT_EXEMPT_PATHS_FILE.is_file()
        else None
    )
    try:
        candidate = resolver.resolve_customization_file(
            marketplace="bento",
            plugin="bento",
            rel_path=_EXEMPT_PATHS_REL_PATH,
            repo_root=root,
            bundled_default_path=bundled_default,
        )
    except ValueError:
        return ()
    if candidate is None:
        return ()
    try:
        lines = candidate.path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    patterns = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return tuple(patterns)


def _path_is_exempt(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _runtime_dir() -> Path:
    """Return an absolute runtime directory, falling back safely to /tmp."""
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if configured:
        candidate = Path(configured)
        if candidate.is_absolute() and candidate.is_dir():
            return candidate
    return Path("/tmp")


def _turn_hold_path(session_id: str) -> Path | None:
    """Return the one-turn hold marker for a safe runtime session ID.

    The marker is deliberately outside the repository so a teammate can honor
    a coordinating lead's temporary hold without changing shared project
    configuration or making the worktree dirtier. This is cooperative, not a
    trusted authorization mechanism. Session IDs are runtime input, so reject
    path-shaped values before incorporating one into a filename.
    """
    if not session_id or set(session_id) <= {"."}:
        return None
    if any(not (character.isalnum() or character in "._-") for character in session_id):
        return None
    return _runtime_dir() / f"{TURN_HOLD_PREFIX}{session_id}"


def consume_turn_hold(session_id: str) -> bool:
    """Consume a cooperative, session-scoped hold for one Stop boundary."""
    path = _turn_hold_path(session_id)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


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


def _swarm_discover_script() -> Path | None:
    """Locate swarm-discover.py relative to this hook's own location.

    Catalog and generated-plugin trees nest hooks/ and skills/ at different
    relative depths (``catalog/hooks/bento/<agent>/scripts/`` vs
    ``plugins/<agent>/bento/hooks/scripts/``), so try both candidate depths
    rather than assume one layout.
    """
    candidates = (
        SCRIPT_DIR.parents[3] / "skills" / "swarm" / "scripts" / "swarm-discover.py",
        SCRIPT_DIR.parents[1] / "skills" / "swarm" / "scripts" / "swarm-discover.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


_SWARM_CONFIG_CANDIDATES = (
    "swarm-config.json",
    ".claude/swarm-config.json",
    ".codex/swarm-config.json",
)


def _has_swarm_config(root: str) -> bool:
    """Cheap existence check before paying for a swarm-discover.py fork.

    The overwhelming majority of repos this hook fires in have no swarm
    config at all, so avoid spawning a Python subprocess (which itself does
    layered config-file resolution) on every single session end just to
    learn that.
    """
    return any((Path(root) / candidate).is_file() for candidate in _SWARM_CONFIG_CANDIDATES)


def is_land_work_integration_worktree(root: str) -> bool:
    """True when root is the repo's configured landing.integration_worktree
    and holds no foreign untracked content.

    Unlike a scratch land-work preview (name-prefix + detached-HEAD check
    above), the persistent integration worktree (bento-96ua.1) has a
    user-chosen path and name, and is not always detached once reused. It is
    exempt from the push/dirty check for the same underlying reason: it never
    accumulates real work of its own, since every commit or staged change
    inside it is fully reproducible by re-running the merge preview from the
    base and feature branches.

    An untracked, non-ignored file is the exception: nothing in this
    worktree's own lifecycle produces one (land-work-create-preview.py's
    integration_worktree_unusable_reason() refuses to reuse it precisely
    because of this), so its presence means a person or another tool put
    real, non-reproducible work there. That must still block the session end
    like any other worktree — silently exempting it here would let
    land-work's next `git reset --hard` discard it unnoticed.
    """
    if not _has_swarm_config(root):
        return False
    script = _swarm_discover_script()
    if script is None:
        return False
    result = subprocess.run(
        [str(script), "--runtime", "auto"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    landing = payload.get("landing")
    if not isinstance(landing, dict):
        return False
    integration_worktree = landing.get("integration_worktree")
    if not integration_worktree:
        return False
    try:
        if Path(integration_worktree).resolve() != Path(root).resolve():
            return False
    except OSError:
        return False
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=normal")
    if status.returncode != 0:
        return False
    return not any(line.startswith("??") for line in status.stdout.splitlines())


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


def has_only_exempt_dirty_changes(root: str, patterns: tuple[str, ...]) -> bool:
    """Whether every dirty record matches a configured exempt-path pattern.

    Porcelain v1 with ``-z`` puts a rename or copy destination in the first
    record and its source in the next one. Both paths must match. Untracked
    changes and an unparseable status fail closed. No configured patterns
    means nothing is exempt.
    """
    if not patterns:
        return False

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
        if status == "??" or not _path_is_exempt(path, patterns):
            return False
        saw_change = True
        if "R" in status or "C" in status:
            if index >= len(records):
                return False
            source_path = records[index]
            index += 1
            if not source_path or not _path_is_exempt(source_path, patterns):
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


def has_only_exempt_ahead_commits(root: str, patterns: tuple[str, ...]) -> bool:
    """Whether every commit ahead of upstream touches only exempt paths.

    ``-m`` compares a merge against every parent, so a source change hidden by
    one parent still keeps the Stop hook blocking. Any Git failure fails
    closed. No configured patterns means nothing is exempt.
    """
    if not patterns:
        return False

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
        if not paths or any(not _path_is_exempt(path, patterns) for path in paths):
            return False
    return True


def _classify_problems(root: str, dirty: bool) -> list[tuple[str, str]]:
    """Return (kind, human-readable text) pairs for each active problem.

    ``kind`` is a stable category ("dirty", "unpushed") used to detect
    whether the *shape* of the problem changed between turns, independent of
    the exact count in the text (which is expected to keep changing, e.g. as
    unpushed commits accumulate).
    """
    problems: list[tuple[str, str]] = []
    # Resolved lazily, at most once: a clean, fully pushed tree (the common
    # case) never needs the exempt-paths file read at all.
    patterns: tuple[str, ...] | None = None
    if dirty:
        patterns = dirty_state_exempt_patterns(root)
        if not has_only_exempt_dirty_changes(root, patterns):
            problems.append(("dirty", "uncommitted changes"))

    # A missing upstream is a warning, not a block, so worktree flows that have
    # not pushed a first commit are not trapped. Only count ahead commits when
    # an upstream exists.
    if has_upstream(root):
        ahead = ahead_count(root)
        if ahead > 0 and patterns is None:
            patterns = dirty_state_exempt_patterns(root)
        if ahead > 0 and not has_only_exempt_ahead_commits(root, patterns or ()):
            noun = "commit" if ahead == 1 else "commits"
            problems.append(("unpushed", f"{ahead} unpushed {noun}"))

    return problems


def _render_full_block_message(
    root: str, problems: list[tuple[str, str]], session_id: str
) -> str:
    branch = current_branch(root) or "(detached HEAD)"
    joined = " and ".join(text for _, text in problems)
    message = (
        f"Session end blocked: branch '{branch}' has {joined}.\n"
        "Commit and push your work before ending the session. Note: Stop fires "
        "at the end of every turn, not only when the session truly ends, so "
        "this can block mid-session too. "
        "To suppress this check for this repo, add 'require_pushed=false' to "
        ".agent-mode.local.\n"
    )
    if _turn_hold_path(session_id) is not None:
        marker_name = f"{TURN_HOLD_PREFIX}{session_id}"
        message += (
            "If your coordinating lead explicitly instructed you to hold work "
            "open, create the session marker "
            f"'{marker_name}' under $XDG_RUNTIME_DIR (or /tmp) before yielding. "
            "It permits exactly one Stop boundary and is then consumed.\n"
        )
    return message


def _render_condensed_block_message(root: str, problems: list[tuple[str, str]]) -> str:
    branch = current_branch(root) or "(detached HEAD)"
    joined = " and ".join(text for _, text in problems)
    return (
        f"Session end still blocked: branch '{branch}' has {joined} "
        "(unchanged in kind since an earlier turn this session -- see that "
        "message for remediation).\n"
    )


# --- pushed-but-not-landed advisory (bento-rdtn.11) -------------------------


def is_landed_check_suppressed(root: str) -> bool:
    """True when .agent-mode.local sets require_landed=false. Independent of
    require_pushed=false, which suppresses the (separate) blocking check
    above."""
    return _agent_mode_flag_is_false(root, "require_landed")


def is_landed_on_primary(root: str, primary: str) -> bool:
    """True when HEAD's content is already on origin/<primary> -- either as
    a real ancestor (a merge commit or fast-forward), or patch-equivalent
    (every commit shows as "-" in `git cherry`: same diff, different SHA).
    The ancestor check alone is not enough: a squash-merge or rebase-merge
    (e.g. GitHub's default "Squash and merge") lands the branch's content
    without HEAD ever becoming an ancestor of the target, which would
    otherwise make a genuinely landed branch look permanently unlanded.
    Mirrors closure-scan.py's own unique_patch_count == 0 patch-equivalence
    check for the identical reason."""
    if _git(root, "merge-base", "--is-ancestor", "HEAD", f"origin/{primary}").returncode == 0:
        return True
    cherry = _git(root, "cherry", f"origin/{primary}", "HEAD")
    if cherry.returncode != 0:
        return False
    lines = [line for line in cherry.stdout.splitlines() if line.strip()]
    return all(line.startswith("-") for line in lines)


def detect_primary_branch(root: str) -> str:
    """Best-effort primary branch name, mirroring land-work's git_state.py
    detect_primary_branch(): origin/HEAD's symref, else a local or
    remote-tracking main/master ref, else the current branch itself -- so an
    unconventional repo with neither never has its only branch treated as
    "not landed" against itself."""
    result = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    origin_head = result.stdout.strip()
    if result.returncode == 0 and origin_head:
        return origin_head.removeprefix("origin/")
    for candidate in ("main", "master"):
        if (
            _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}").returncode == 0
            or _git(
                root, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{candidate}"
            ).returncode
            == 0
        ):
            return candidate
    return current_branch(root)


def pushed_but_unlanded_primary(root: str, branch: str) -> str | None:
    """Return the detected primary branch name when `branch` is clean (the
    caller checks this), has an upstream with zero unpushed commits, is not
    the primary branch, and is not yet an ancestor of origin/<primary> --
    i.e. genuinely parked, pushed work. Returns None otherwise, including
    detached HEAD (branch == "") and when origin/<primary> cannot be
    resolved locally (fail toward silence, not a guess)."""
    if not branch or not has_upstream(root) or ahead_count(root) > 0:
        return None
    primary = detect_primary_branch(root)
    if branch == primary:
        return None
    remote_primary_ref = f"refs/remotes/origin/{primary}"
    if _git(root, "rev-parse", "--verify", "--quiet", remote_primary_ref).returncode != 0:
        return None
    if is_landed_on_primary(root, primary):
        return None
    return primary


def _throttle_state_path(session_id: str) -> Path:
    return _runtime_dir() / f"bento-check-unpushed-{session_id}.json"


def _read_session_state(session_id: str) -> dict:
    """Lock-free read of the whole per-session state file. A read racing a
    concurrent locked write (below) can at worst see stale state, which fails
    toward showing a message again, never toward wrongly suppressing one."""
    if not session_id:
        return {}
    try:
        data = json.loads(_throttle_state_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _update_session_state(session_id: str, mutate) -> None:
    """Locked read-modify-write of the whole per-session state file. Two Stop
    invocations for the same session firing close together must not race and
    drop one's update (a plain read-then-write, each on its own copy of the
    pre-update state, could otherwise let a third invocation see neither)."""
    if not session_id:
        return
    path = _throttle_state_path(session_id)
    try:
        with open(path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            try:
                data = json.loads(handle.read() or "{}")
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            mutate(data)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(data))
    except OSError:
        pass


def already_advised_this_session(session_id: str, root: str, branch: str) -> bool:
    """No session_id (an unexpected payload shape) fails toward showing the
    advisory rather than silently throttling forever."""
    advised = _read_session_state(session_id).get("advised")
    return isinstance(advised, list) and f"{root}:{branch}" in advised


def record_advised_this_session(session_id: str, root: str, branch: str) -> None:
    def mutate(data: dict) -> None:
        advised = set(data.get("advised", [])) if isinstance(data.get("advised"), list) else set()
        advised.add(f"{root}:{branch}")
        data["advised"] = sorted(advised)

    _update_session_state(session_id, mutate)


def previous_block_kinds(session_id: str, root: str, branch: str) -> frozenset[str] | None:
    """The set of problem kinds ("dirty", "unpushed") blocked last time in
    this session for this (root, branch), or None if nothing was recorded yet
    (including when there is no session_id to key on)."""
    blocked = _read_session_state(session_id).get("blocked_kinds")
    if not isinstance(blocked, dict):
        return None
    kinds = blocked.get(f"{root}:{branch}")
    if not isinstance(kinds, list):
        return None
    return frozenset(kinds)


def record_block_kinds(session_id: str, root: str, branch: str, kinds: frozenset[str]) -> None:
    def mutate(data: dict) -> None:
        blocked = data.get("blocked_kinds")
        if not isinstance(blocked, dict):
            blocked = {}
        blocked[f"{root}:{branch}"] = sorted(kinds)
        data["blocked_kinds"] = blocked

    _update_session_state(session_id, mutate)


def clear_block_kinds(session_id: str, root: str, branch: str) -> None:
    """Forget a recorded block for this (root, branch) once it resolves.

    Without this, an unrelated *later* recurrence of the same problem kind
    (e.g. the branch goes clean, then goes dirty again for a different
    reason) would be wrongly condensed as "unchanged since an earlier turn,"
    even though the earlier full message already scrolled out of view and
    this is a fresh occurrence, not a repeat.
    """
    def mutate(data: dict) -> None:
        blocked = data.get("blocked_kinds")
        if isinstance(blocked, dict):
            blocked.pop(f"{root}:{branch}", None)

    _update_session_state(session_id, mutate)


def evaluate(hook_input: dict) -> tuple[str | None, str | None]:
    """Return (block_reason, advisory_message) -- at most one is non-None.
    Shares the root resolution and worktree-kind/in-progress-operation
    exemptions between the two checks instead of recomputing them twice per
    Stop invocation (they read from the same repo state either way)."""
    if hook_input.get("stop_hook_active"):
        return None, None

    cwd = hook_input.get("cwd") or ""
    if not cwd or not os.path.isdir(cwd):
        return None, None

    root = repo_root(cwd)
    if root is None:
        return None, None

    if is_land_work_preview(root):
        return None, None

    if is_land_work_integration_worktree(root):
        return None, None

    if has_in_progress_operation(root):
        return None, None

    dirty = is_dirty(root)
    session_id = hook_input.get("session_id") or ""
    branch = current_branch(root)
    problems = _classify_problems(root, dirty)

    if not is_suppressed(root) and problems:
        if consume_turn_hold(session_id):
            return None, None
        kinds = frozenset(kind for kind, _ in problems)
        previous_kinds = previous_block_kinds(session_id, root, branch)
        if previous_kinds == kinds:
            return _render_condensed_block_message(root, problems), None
        record_block_kinds(session_id, root, branch, kinds)
        return _render_full_block_message(root, problems, session_id), None

    # No active block this turn: forget any prior recorded state so a later,
    # unrelated recurrence of the same problem kind is treated as fresh
    # rather than wrongly condensed as "unchanged since an earlier turn."
    clear_block_kinds(session_id, root, branch)

    if is_landed_check_suppressed(root):
        return None, None

    if dirty:
        return None, None  # the blocking check above already covers a dirty tree

    primary = pushed_but_unlanded_primary(root, branch)
    if primary is None:
        return None, None

    if already_advised_this_session(session_id, root, branch):
        return None, None
    record_advised_this_session(session_id, root, branch)

    return None, (
        f"'{branch}' is pushed but not landed on '{primary}' — run "
        "bento:land-work (or bento:closure for abandoned work).\n"
    )


def main() -> int:
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        # Never break session stop on a malformed payload.
        return 0
    try:
        reason, advisory = evaluate(hook_input)
    except Exception:
        # Never break session stop on an unexpected git/filesystem error.
        return 0
    if reason:
        # Exit code 2 is the documented Stop blocking signal for Claude Code:
        # the stderr message is fed back to the model. Exit 1 is a non-blocking
        # failure and lets the stop proceed, so the hook must use 2 to block.
        sys.stderr.write(reason)
        return 2
    if advisory:
        sys.stderr.write(advisory)
    return 0


if __name__ == "__main__":
    sys.exit(main())
