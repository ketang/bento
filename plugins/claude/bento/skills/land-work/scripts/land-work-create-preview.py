#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from git_state import (
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
    return parser.parse_args()


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
    result = subprocess.run(
        [str(_SWARM_DISCOVER), "--runtime", runtime],
        cwd=checkout_root,
        capture_output=True,
        text=True,
    )
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
    if preview_dir not in registered_worktree_paths(checkout_root):
        return f"landing.integration_worktree at {preview_dir} exists but is not a registered git worktree"
    status = git_stdout("status", "--porcelain=v1", "--untracked-files=normal", cwd=preview_dir)
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

    persistent_worktree = False
    if args.preview_dir:
        preview_dir = Path(args.preview_dir).resolve()
    else:
        integration_worktree, iw_warnings = resolve_integration_worktree(checkout_root, args.runtime)
        warnings.extend(iw_warnings)
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

    base_sha = rev_parse(base_ref, checkout_root) if not errors else None
    feature_sha = rev_parse(feature_ref, checkout_root) if not errors else None

    if not errors and persistent_worktree and preview_dir.exists():
        reason = integration_worktree_unusable_reason(preview_dir, checkout_root)
        if reason:
            warnings.append(f"{reason}; falling back to a scratch preview directory")
            preview_dir = default_preview_dir()
            persistent_worktree = False

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
        "conflicting_paths": conflicting_paths,
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
    }

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
