#!/usr/bin/env python3
"""Assemble a batch of branches into one merge-commit chain (bento-96ua.3).

Given an already-resolved worktree (typically the repo's persistent
landing.integration_worktree — see land-work-create-preview.py and
swarm/references/landing-config.md) and an ordered list of branches, this
resets the worktree to the leased base and merges each branch in turn with
an explicit merge commit, preserving per-branch history. A branch that
conflicts (or does not resolve to a commit) is evicted: its merge is
aborted, the worktree is left exactly as it was before that branch was
attempted, and assembly continues with the remaining branches. Gating the
assembled tip (landing.full_gate), re-verifying the primary-branch lease
(land-work-verify-lease.py), and pushing are separate steps this script does
not perform — it only produces the candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from git_state import (
    detect_checkout_root,
    git,
    git_stdout,
    registered_worktree_paths,
    rev_exists,
    rev_parse,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", required=True, help="worktree to assemble the batch into")
    parser.add_argument("--base-ref", required=True, help="leased base revision to reset the worktree to before assembling")
    parser.add_argument(
        "--branch",
        action="append",
        default=[],
        dest="branches",
        help="branch to merge, in order; repeat for each branch in the batch",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    worktree = Path(args.worktree).resolve()

    errors: list[str] = []
    if worktree not in registered_worktree_paths(checkout_root):
        errors.append(f"{worktree} is not a registered git worktree of {checkout_root}")
    if not rev_exists(args.base_ref, checkout_root):
        errors.append(f"base revision does not exist: {args.base_ref}")

    if errors:
        payload = {
            "cwd": str(cwd),
            "checkout_root": str(checkout_root),
            "worktree": str(worktree),
            "base_ref": args.base_ref,
            "base_sha": None,
            "assembled": [],
            "evicted": [],
            "tip_sha": None,
            "tip_tree": None,
            "ok": False,
            "errors": errors,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    base_sha = rev_parse(args.base_ref, checkout_root)
    # `reset --hard` clears any leftover merge state (including an
    # in-progress MERGE_HEAD) from a prior attempt, the same way
    # land-work-create-preview.py's persistent-worktree reuse path does.
    git("reset", "--hard", base_sha, cwd=worktree)

    assembled: list[dict[str, object]] = []
    evicted: list[dict[str, object]] = []

    for branch in args.branches:
        if not rev_exists(branch, checkout_root):
            evicted.append({"branch": branch, "reason": f"revision does not exist: {branch}", "conflicting_paths": []})
            continue
        branch_sha = rev_parse(branch, checkout_root)
        merge_result = git("merge", "--no-ff", branch_sha, "-m", f"batch: merge {branch}", cwd=worktree, check=False)
        if merge_result.returncode == 0:
            assembled.append(
                {
                    "branch": branch,
                    "branch_sha": branch_sha,
                    "merge_commit_sha": git_stdout("rev-parse", "HEAD", cwd=worktree),
                }
            )
            continue
        conflicting_paths = [
            line
            for line in git_stdout("diff", "--name-only", "--diff-filter=U", cwd=worktree).splitlines()
            if line
        ]
        git("merge", "--abort", cwd=worktree, check=False)
        reason = "conflict" if conflicting_paths else (merge_result.stderr.strip() or "merge failed")
        evicted.append({"branch": branch, "reason": reason, "conflicting_paths": conflicting_paths})

    payload = {
        "cwd": str(cwd),
        "checkout_root": str(checkout_root),
        "worktree": str(worktree),
        "base_ref": args.base_ref,
        "base_sha": base_sha,
        "assembled": assembled,
        "evicted": evicted,
        "tip_sha": git_stdout("rev-parse", "HEAD", cwd=worktree),
        "tip_tree": git_stdout("rev-parse", "HEAD^{tree}", cwd=worktree),
        "ok": True,
        "errors": [],
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
