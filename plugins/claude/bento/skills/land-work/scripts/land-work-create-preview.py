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
    rev_exists,
    rev_parse,
    working_tree_dirty,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", help="base revision to preview against; defaults to origin/<primary-branch> when available")
    parser.add_argument("--feature-ref", help="feature revision to merge; defaults to the current branch")
    parser.add_argument("--preview-dir", help="directory to materialize the merge preview into")
    return parser.parse_args()


def default_preview_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="land-work-preview-", dir="/tmp")).resolve()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    primary_branch, warnings = detect_primary_branch(checkout_root)
    branch = current_branch(checkout_root)
    default_base_ref = (
        f"refs/remotes/origin/{primary_branch}"
        if ref_exists(f"refs/remotes/origin/{primary_branch}", checkout_root)
        else f"refs/heads/{primary_branch}"
    )
    base_ref = args.base_ref or default_base_ref
    feature_ref = args.feature_ref or branch
    preview_dir = Path(args.preview_dir).resolve() if args.preview_dir else default_preview_dir()

    errors: list[str] = []
    conflicting_paths: list[str] = []
    preview_tree = None
    merge_clean = False

    if working_tree_dirty(checkout_root):
        errors.append("working tree is dirty")
    if not rev_exists(base_ref, checkout_root):
        errors.append(f"base revision does not exist: {base_ref}")
    if not rev_exists(feature_ref, checkout_root):
        errors.append(f"feature revision does not exist: {feature_ref}")

    base_sha = rev_parse(base_ref, checkout_root) if not errors else None
    feature_sha = rev_parse(feature_ref, checkout_root) if not errors else None

    if not errors:
        try:
            git("worktree", "add", "--detach", str(preview_dir), base_sha, cwd=checkout_root)
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
        except subprocess.CalledProcessError as exc:
            errors.append(exc.stderr.strip() or str(exc))

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
