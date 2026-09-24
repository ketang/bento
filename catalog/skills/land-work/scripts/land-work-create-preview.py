#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from git_state import (
    NotAWorkTreeError,
    current_branch,
    detect_checkout_root,
    detect_primary_branch,
    git,
    git_stdout,
    is_linked_worktree,
    ref_exists,
    registered_worktree_paths,
    rev_exists,
    rev_parse,
    working_tree_dirty,
)

SCRIPT_DIR = Path(__file__).resolve().parent
# swarm-discover.py lives beside the swarm skill's scripts; both skills sit
# under a shared skills/ root in the catalog and in every generated plugin.
_SWARM_DISCOVER = SCRIPT_DIR.parents[1] / "swarm" / "scripts" / "swarm-discover.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", help="base revision to preview against; defaults to origin/<primary-branch> when available")
    parser.add_argument("--feature-ref", help="feature revision to merge; defaults to the current branch")
    parser.add_argument(
        "--preview-dir",
        help="directory to materialize the merge preview into; required with --cleanup. "
        "Overrides any configured landing.integration_worktree.",
    )
    parser.add_argument(
        "--runtime",
        choices=("auto", "claude", "codex"),
        default="auto",
        help="runtime hint passed to swarm-discover.py when resolving landing.integration_worktree",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove a previously-created preview worktree at --preview-dir; idempotent if the directory is already gone. "
        "Refuses (without error) when --preview-dir is the repo's configured landing.integration_worktree.",
    )
    parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="skip the leftover-preview-worktree check and create a new preview anyway. "
        "Does NOT protect a live preview owned by another landing.",
    )
    parser.add_argument(
        "--owner-pid",
        type=int,
        help="pid of a long-lived process (e.g. land.py) that owns the new preview for its whole lifetime; "
        "recorded as owner_kind=driver so a later run can tell whether the preview is still live. "
        "Omit for standalone use (owner_kind=manual, judged by preview mtime instead of pid).",
    )
    return parser.parse_args()


def leftover_preview_worktrees(checkout_root: Path) -> tuple[list[Path], list[str]]:
    """Registered land-work-preview-* worktrees left behind by an earlier,
    uncleaned landing attempt (bento-rdtn.3): each one is a live git worktree
    that slows every later `git worktree` probe until removed.

    Returns (leftovers, warnings). A failure listing worktrees degrades to "no
    leftovers found" (so it never blocks a landing on a git plumbing hiccup)
    but is surfaced as a warning rather than silently swallowed, matching how
    the same failure is handled elsewhere in this file (e.g.
    integration_worktree_unusable_reason)."""
    try:
        registered = registered_worktree_paths(checkout_root)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        return [], [
            "unable to check for leftover land-work-preview-* worktrees "
            f"(`git worktree list` failed: {stderr or exc})"
        ]
    leftovers = sorted(p for p in registered if p.name.startswith("land-work-preview-"))
    return leftovers, []


OWNER_FILE = "land-work-owner.json"
LOCK_FILE = "land-work-preview.lock"


def preview_admin_dir(preview: Path) -> Path | None:
    try:
        out = git_stdout("rev-parse", "--absolute-git-dir", cwd=preview)
    except (subprocess.CalledProcessError, OSError):
        return None
    return Path(out.strip()) if out.strip() else None


def proc_start_time(pid: int) -> str | None:
    """Field 22 of /proc/<pid>/stat (clock ticks since boot); None if it
    cannot be read, whether the pid is gone or /proc is unavailable."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return raw.rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def pid_namespace() -> str | None:
    try:
        return os.readlink("/proc/self/ns/pid")
    except OSError:
        return None


def boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_owner_file(
    preview: Path, owner_pid: int | None, feature_ref: str | None, base_sha: str | None
) -> str | None:
    """Record who owns a new preview inside its git admin dir (never the
    working tree, so it cannot dirty or be staged). Returns an error message on
    failure. owner_kind=driver means owner_pid is a long-lived process whose
    death proves the preview abandoned; manual (standalone) previews record
    the parent pid for information only and are never auto-reclaimed."""
    admin = preview_admin_dir(preview)
    if admin is None:
        return f"unable to locate git dir of {preview}; preview owner not recorded"
    pid = owner_pid if owner_pid is not None else os.getppid()
    info = {
        "owner_kind": "driver" if owner_pid is not None else "manual",
        "pid": pid,
        "pid_start_time": proc_start_time(pid),
        "hostname": socket.gethostname(),
        "pid_ns": pid_namespace(),
        "boot_id": boot_id(),
        "session_id": os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CODEX_SESSION_ID"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_branch": feature_ref,
        "base_sha": base_sha,
    }
    tmp = admin / f"{OWNER_FILE}.tmp"
    try:
        tmp.write_text(json.dumps(info), encoding="utf-8")
        os.replace(tmp, admin / OWNER_FILE)
    except OSError as exc:
        return f"unable to record preview owner in {admin} ({exc})"
    return None


def read_owner_file(admin: Path | None) -> dict | None:
    if admin is None:
        return None
    try:
        info = json.loads((admin / OWNER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def classify_leftover(preview: Path) -> tuple[str, str]:
    """Return (state, description); state is "dead" only when abandonment is
    PROVEN, otherwise "live" or "unknown". Anything unobservable is unknown
    (fail closed, bento-e583): a missing/unparseable owner file, a manual
    owner, another host, pid namespace or boot, a missing recorded start time,
    an unreadable /proc, or a preview holding a commit beyond its recorded
    base (a driver may have died mid push-from-preview)."""
    if not preview.exists():
        return "dead", f"{preview} (directory already gone)"
    admin = preview_admin_dir(preview)
    info = read_owner_file(admin) or {}
    pid = info.get("pid")
    kind = info.get("owner_kind")
    desc = (
        f"{preview} (owner_kind={kind or 'none'}, pid={pid}, session={info.get('session_id')}, "
        f"branch={info.get('feature_branch')}, created {info.get('created_at')})"
    )
    if kind != "driver" or type(pid) is not int or pid <= 0:
        return "unknown", desc
    recorded_start = info.get("pid_start_time")
    here_ns, here_boot = pid_namespace(), boot_id()
    if (
        not isinstance(recorded_start, str)
        or not recorded_start
        or info.get("hostname") != socket.gethostname()
        or not here_ns
        or not here_boot
        or info.get("pid_ns") != here_ns
        or info.get("boot_id") != here_boot
    ):
        return "unknown", desc
    start = proc_start_time(pid)
    if start is None:
        # Unreadable stat proves death only if /proc is mounted and lists no such pid.
        if proc_start_time(os.getpid()) is None or Path(f"/proc/{pid}").exists():
            return "unknown", desc
    elif start == recorded_start:
        return "live", desc
    base = info.get("base_sha")
    try:
        head = git_stdout("rev-parse", "HEAD", cwd=preview).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown", desc
    if not base or head != base:
        return "unknown", desc + f" holds commit {head[:12]} beyond its base; may be an interrupted landing"
    return "dead", desc


def classify_leftovers(leftovers: list[Path], reclaim_allowed: bool) -> tuple[list[Path], list[Path], list[str]]:
    """Split leftovers into (dead, remaining, descriptions of remaining).
    With reclaim_allowed False, dead ones are reported as remaining too."""
    dead: list[Path] = []
    remaining: list[Path] = []
    described: list[str] = []
    for path in leftovers:
        state, desc = classify_leftover(path)
        if state == "dead" and reclaim_allowed:
            dead.append(path)
        else:
            remaining.append(path)
            described.append(f"{state}: {desc}")
    return dead, remaining, described


def reclaim_dead_leftovers(checkout_root: Path, dead: list[Path]) -> tuple[list[str], list[str]]:
    """Remove leftovers still provably dead. Re-classifies under a lock in the
    common git dir so two sessions cannot both remove (or misjudge) one.
    Returns (reclaimed paths, errors)."""
    reclaimed: list[str] = []
    errors: list[str] = []
    common = git_stdout("rev-parse", "--git-common-dir", cwd=checkout_root).strip()
    lock_path = (checkout_root / common).resolve() / LOCK_FILE
    with open(lock_path, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in dead:
            state, desc = classify_leftover(path)
            if state != "dead":
                errors.append(f"leftover preview no longer provably dead, not reclaimed: {state}: {desc}")
                continue
            if path.exists():
                removed, errs = cleanup_preview(path, checkout_root)
                if not removed and errs and path.exists():
                    errors.append(f"unable to reclaim {path}: {'; '.join(errs)}")
                    continue
            git("worktree", "prune", cwd=checkout_root, check=False)
            reclaimed.append(str(path))
    return reclaimed, errors


def default_preview_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="land-work-preview-", dir="/tmp")).resolve()


def resolve_integration_worktree(checkout_root: Path, runtime: str) -> tuple[Path | None, list[str]]:
    """Resolve swarm-config.json's landing.integration_worktree, if any.

    Fails safe: any problem reaching or parsing swarm-discover.py degrades to
    "no configured integration worktree" (the caller then falls back to a
    scratch /tmp preview) rather than blocking the landing.
    """
    if not _SWARM_DISCOVER.is_file():
        return None, []
    try:
        result = subprocess.run(
            [str(_SWARM_DISCOVER), "--runtime", runtime],
            cwd=checkout_root,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return None, [
            f"unable to run swarm-discover.py while resolving landing.integration_worktree ({exc}); "
            "using a scratch preview directory"
        ]
    if result.returncode != 0:
        return None, [
            f"swarm-discover.py exited {result.returncode} while resolving landing.integration_worktree; "
            "using a scratch preview directory"
        ]
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, [
            "swarm-discover.py produced invalid JSON while resolving landing.integration_worktree; "
            "using a scratch preview directory"
        ]
    landing = payload.get("landing")
    if not isinstance(landing, dict):
        return None, []
    integration_worktree = landing.get("integration_worktree")
    if not integration_worktree:
        return None, []
    return Path(integration_worktree), []


def integration_worktree_unusable_reason(preview_dir: Path, checkout_root: Path) -> str | None:
    """Return why a configured integration worktree cannot be reused, if any.

    Tracked modifications are not disqualifying: they can only be this
    script's own leftover --no-commit merge state from a prior preview (or
    landing) and `git reset --hard` clears them, including any in-progress
    MERGE_HEAD, before the next merge attempt. Only untracked, non-ignored
    files disqualify reuse — nothing in this worktree's own lifecycle ever
    creates those, so their presence means something else (a person, another
    tool) touched the shared worktree and it must not be silently reset.
    """
    try:
        registered = registered_worktree_paths(checkout_root)
    except subprocess.CalledProcessError:
        return f"unable to list registered worktrees in {checkout_root} (`git worktree list` failed)"
    if preview_dir not in registered:
        return f"landing.integration_worktree at {preview_dir} exists but is not a registered git worktree"
    try:
        status = git_stdout("status", "--porcelain=v1", "--untracked-files=normal", cwd=preview_dir)
    except subprocess.CalledProcessError:
        return (
            f"landing.integration_worktree at {preview_dir} is registered but `git status` failed "
            "in it (corrupted or partially removed worktree)"
        )
    foreign_untracked = [line[3:] for line in status.splitlines() if line.startswith("??")]
    if foreign_untracked:
        return (
            f"landing.integration_worktree at {preview_dir} has untracked files: "
            + ", ".join(foreign_untracked)
        )
    return None


def cleanup_preview(preview_dir: Path, checkout_root: Path) -> tuple[bool, list[str]]:
    """Remove a registered preview worktree. Idempotent when the dir is gone."""
    errors: list[str] = []
    if not preview_dir.exists():
        return False, errors
    result = git("worktree", "remove", "--force", str(preview_dir), cwd=checkout_root, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        errors.append(stderr or f"git worktree remove failed for {preview_dir}")
        return False, errors
    return True, errors


def main() -> int:
    args = parse_args()
    if args.owner_pid is not None and args.owner_pid <= 0:
        print("--owner-pid must be a positive pid", file=sys.stderr)
        return 2
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    primary_branch, warnings = detect_primary_branch(checkout_root)
    branch = current_branch(checkout_root)

    if args.cleanup:
        if not args.preview_dir:
            print("--cleanup requires --preview-dir", file=sys.stderr)
            return 2
        preview_dir = Path(args.preview_dir).resolve()
        integration_worktree, iw_warnings = resolve_integration_worktree(checkout_root, args.runtime)
        warnings.extend(iw_warnings)
        if integration_worktree is not None and preview_dir == integration_worktree.resolve():
            payload = {
                "cwd": str(cwd),
                "checkout_root": str(checkout_root),
                "preview_dir": str(preview_dir),
                "cleaned_up": False,
                "ok": True,
                "warnings": warnings
                + [
                    f"refusing to remove landing.integration_worktree at {preview_dir}; "
                    "it is meant to persist across landings"
                ],
                "errors": [],
            }
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        if iw_warnings:
            # resolve_integration_worktree()'s fail-safe default ("no
            # configured worktree") is correct for the create-preview flow,
            # where the caller then falls back to a scratch directory. It is
            # wrong here: acting on it would force-remove --preview-dir even
            # when it genuinely is the persistent worktree, just because
            # discovery hiccuped — reintroducing the "persistent worktree
            # deleted" failure mode via a different trigger. Refuse instead
            # of guessing.
            payload = {
                "cwd": str(cwd),
                "checkout_root": str(checkout_root),
                "preview_dir": str(preview_dir),
                "cleaned_up": False,
                "ok": False,
                "warnings": warnings,
                "errors": [
                    "unable to confirm whether --preview-dir is the configured "
                    "landing.integration_worktree; refusing to remove it"
                ],
            }
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 1
        cleaned_up, errors = cleanup_preview(preview_dir, checkout_root)
        payload = {
            "cwd": str(cwd),
            "checkout_root": str(checkout_root),
            "preview_dir": str(preview_dir),
            "cleaned_up": cleaned_up,
            "ok": not errors,
            "warnings": warnings,
            "errors": errors,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if payload["ok"] else 1
    default_base_ref = (
        f"refs/remotes/origin/{primary_branch}"
        if ref_exists(f"refs/remotes/origin/{primary_branch}", checkout_root)
        else f"refs/heads/{primary_branch}"
    )
    base_ref = args.base_ref or default_base_ref
    feature_ref = args.feature_ref or branch

    integration_worktree, iw_warnings = resolve_integration_worktree(checkout_root, args.runtime)
    if not args.preview_dir:
        warnings.extend(iw_warnings)

    reclaimed_previews: list[str] = []
    dead_leftovers: list[Path] = []
    if not args.allow_existing:
        leftover, leftover_warnings = leftover_preview_worktrees(checkout_root)
        warnings.extend(leftover_warnings)
        if integration_worktree is not None:
            # A configured persistent worktree is never a reclaim candidate.
            leftover = [p for p in leftover if p != integration_worktree.resolve()]
        # Unconfirmed integration-worktree config: reclaim nothing (fail closed).
        dead_leftovers, leftover, described = classify_leftovers(leftover, reclaim_allowed=not iw_warnings)
        if leftover:
            cleanup_hint = "; ".join(
                f"land-work-create-preview.py --cleanup --preview-dir {p}" for p in leftover
            )
            payload = {
                "cwd": str(cwd),
                "checkout_root": str(checkout_root),
                "branch": branch,
                "primary_branch": primary_branch,
                "linked_worktree": is_linked_worktree(checkout_root),
                "leftover_previews": [str(p) for p in leftover],
                "reclaimed_previews": reclaimed_previews,
                "ok": False,
                "warnings": warnings,
                "errors": [
                    "leftover land-work-preview-* worktree(s) exist (owner live or not proven dead; not reclaimed): "
                    + "; ".join(described)
                    + f"; wait for the owner, or if you are sure it is abandoned remove it ({cleanup_hint}) "
                    "or pass --allow-existing"
                ],
            }
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 1

    persistent_worktree = False
    if args.preview_dir:
        preview_dir = Path(args.preview_dir).resolve()
    else:
        if integration_worktree is not None:
            preview_dir = integration_worktree.resolve()
            persistent_worktree = True
        else:
            preview_dir = default_preview_dir()

    errors: list[str] = []
    conflicting_paths: list[str] = []
    preview_tree = None
    merge_clean = False
    preview_cleaned_up = False
    reused_worktree = False

    if working_tree_dirty(checkout_root):
        errors.append("working tree is dirty")
    if not rev_exists(base_ref, checkout_root):
        errors.append(f"base revision does not exist: {base_ref}")
    if not rev_exists(feature_ref, checkout_root):
        errors.append(f"feature revision does not exist: {feature_ref}")

    base_sha: str | None = None
    feature_sha: str | None = None
    if not errors:
        # base_ref/feature_ref were confirmed resolvable by rev_exists() above,
        # but that is a separate git call: either can stop resolving between
        # the two calls (concurrent lease refresh, branch cleanup sweep,
        # another swarm agent). Survive that race the same way
        # land-work-batch-assemble.py's equivalent rev_parse call does.
        try:
            base_sha = rev_parse(base_ref, checkout_root)
        except subprocess.CalledProcessError as exc:
            errors.append(
                f"base revision {base_ref!r} stopped resolving before creating preview "
                f"(`git rev-parse` failed: {(exc.stderr or '').strip() or exc})"
            )
        if not errors:
            try:
                feature_sha = rev_parse(feature_ref, checkout_root)
            except subprocess.CalledProcessError as exc:
                errors.append(
                    f"feature revision {feature_ref!r} stopped resolving before creating preview "
                    f"(`git rev-parse` failed: {(exc.stderr or '').strip() or exc})"
                )

    if not errors and persistent_worktree and preview_dir.exists():
        reason = integration_worktree_unusable_reason(preview_dir, checkout_root)
        if reason:
            warnings.append(f"{reason}; falling back to a scratch preview directory")
            preview_dir = default_preview_dir()
            persistent_worktree = False

    # Reclaim only once every validation above passed, so a run that fails
    # anyway never destroys another session's leftovers.
    if not errors and dead_leftovers:
        reclaimed_previews, reclaim_errors = reclaim_dead_leftovers(checkout_root, dead_leftovers)
        errors.extend(reclaim_errors)

    if not errors:
        worktree_added = False
        try:
            if persistent_worktree and preview_dir.exists():
                git("reset", "--hard", base_sha, cwd=preview_dir)
                reused_worktree = True
            else:
                preview_dir.parent.mkdir(parents=True, exist_ok=True)
                git("worktree", "add", "--detach", str(preview_dir), base_sha, cwd=checkout_root)
                worktree_added = True
                owner_error = write_owner_file(preview_dir, args.owner_pid, feature_ref, base_sha)
                if owner_error:
                    # A driver relies on the owner file for liveness; a manual
                    # caller can proceed without one (it is never reclaimed).
                    (errors if args.owner_pid is not None else warnings).append(owner_error)
            if not errors:
                merge_result = git("merge", "--no-ff", "--no-commit", feature_sha, cwd=preview_dir, check=False)
                merge_clean = merge_result.returncode == 0
                if merge_clean:
                    preview_tree = git_stdout("write-tree", cwd=preview_dir)
                else:
                    conflicting_paths = [
                        line
                        for line in git_stdout(
                            "diff",
                            "--name-only",
                            "--diff-filter=U",
                            cwd=preview_dir,
                        ).splitlines()
                        if line
                    ]
                    if conflicting_paths:
                        errors.append("merge preview has conflicts")
                    else:
                        stderr = merge_result.stderr.strip()
                        errors.append(stderr or "unable to create merge preview")
                    if persistent_worktree:
                        # Leave the shared worktree clean for the next landing
                        # attempt instead of removing it (bento-96ua.1) or leaving
                        # a half-merged state behind.
                        git("merge", "--abort", cwd=preview_dir, check=False)
        except subprocess.CalledProcessError as exc:
            errors.append(exc.stderr.strip() or str(exc))
            if persistent_worktree and reused_worktree:
                git("merge", "--abort", cwd=preview_dir, check=False)

        # A scratch preview that did not yield a usable candidate must not
        # leave its worktree behind. Otherwise every conflicting or
        # interrupted landing attempt leaks a /tmp/land-work-preview-*
        # worktree that only a later manual closure sweep removes (bento-gd2).
        # Gate on `errors` (not `merge_clean`) so this also covers a
        # post-merge failure such as write-tree raising after a clean merge;
        # cleanup runs on every failure path while the caller still owns
        # removing a successful preview. A persistent landing.integration_
        # worktree is never removed here — it survives failures so the next
        # landing can still reuse its build caches.
        if worktree_added and errors and not persistent_worktree:
            preview_cleaned_up, cleanup_errors = cleanup_preview(preview_dir, checkout_root)
            errors.extend(cleanup_errors)

    payload = {
        "cwd": str(cwd),
        "checkout_root": str(checkout_root),
        "branch": branch,
        "primary_branch": primary_branch,
        "linked_worktree": is_linked_worktree(checkout_root),
        "base_ref": base_ref,
        "base_sha": base_sha,
        "feature_ref": feature_ref,
        "feature_sha": feature_sha,
        "preview_dir": str(preview_dir),
        "preview_tree": preview_tree,
        "merge_clean": merge_clean,
        "persistent_worktree": persistent_worktree,
        "reused_worktree": reused_worktree,
        "preview_cleaned_up": preview_cleaned_up,
        "reclaimed_previews": reclaimed_previews,
        "conflicting_paths": conflicting_paths,
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
    }

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except NotAWorkTreeError as exc:
        json.dump(exc.diagnostic, sys.stdout, indent=2)
        sys.stdout.write("\n")
        exit_code = 1
    raise SystemExit(exit_code)
