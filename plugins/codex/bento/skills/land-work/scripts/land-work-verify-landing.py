#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import subprocess

from git_state import (
    current_branch,
    detect_checkout_root,
    detect_primary_branch,
    is_linked_worktree,
    ref_exists,
    registered_worktree_paths,
    rev_parse,
    tree_for_ref,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", help="ref to verify; defaults to refs/heads/<primary-branch> when available")
    parser.add_argument("--expected-sha", help="required commit SHA for the landed ref")
    parser.add_argument("--expected-tree", help="required tree SHA for the landed ref")
    parser.add_argument(
        "--preview-dir",
        help="preview worktree path that must no longer be registered (i.e. cleaned up) after landing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    primary_branch, warnings = detect_primary_branch(checkout_root)
    branch = current_branch(checkout_root)
    default_ref = (
        f"refs/heads/{primary_branch}"
        if ref_exists(f"refs/heads/{primary_branch}", checkout_root)
        else f"refs/remotes/origin/{primary_branch}"
    )
    ref = args.ref or default_ref

    errors: list[str] = []
    resolved_sha = None
    resolved_tree = None
    sha_matches = args.expected_sha is None
    tree_matches = args.expected_tree is None

    if not ref_exists(ref, checkout_root):
        errors.append(f"ref does not exist: {ref}")
    else:
        resolved_sha = rev_parse(ref, checkout_root)
        resolved_tree = tree_for_ref(ref, checkout_root)

    if args.expected_sha is not None:
        sha_matches = resolved_sha == args.expected_sha
        if not sha_matches:
            errors.append(f"landed ref mismatch for {ref}")
    if args.expected_tree is not None:
        tree_matches = resolved_tree == args.expected_tree
        if not tree_matches:
            errors.append(f"landed tree mismatch for {ref}")

    preview_dir_registered = None
    if args.preview_dir:
        preview_path = Path(args.preview_dir).resolve()
        try:
            registered = registered_worktree_paths(checkout_root)
        except subprocess.CalledProcessError:
            errors.append(
                f"unable to list registered worktrees in {checkout_root} (`git worktree list` failed)"
            )
        else:
            preview_dir_registered = preview_path in registered
            if preview_dir_registered:
                errors.append(
                    f"preview worktree still registered: {preview_path} (run "
                    f"land-work-create-preview.py --cleanup --preview-dir {preview_path})"
                )

    payload = {
        "cwd": str(cwd),
        "checkout_root": str(checkout_root),
        "branch": branch,
        "primary_branch": primary_branch,
        "linked_worktree": is_linked_worktree(checkout_root),
        "ref": ref,
        "resolved_sha": resolved_sha,
        "resolved_tree": resolved_tree,
        "expected_sha": args.expected_sha,
        "expected_tree": args.expected_tree,
        "sha_matches": sha_matches,
        "tree_matches": tree_matches,
        "preview_dir": str(args.preview_dir) if args.preview_dir else None,
        "preview_dir_registered": preview_dir_registered,
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
    }

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
