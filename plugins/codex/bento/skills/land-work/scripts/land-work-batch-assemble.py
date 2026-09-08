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

Every git call after the initial validation runs in a worktree shared with
other swarm agents across the lifetime of this process, so any of them can
start failing partway through assembly (the worktree can be reset, removed,
or corrupted by someone else between two of our own calls). Every such call
is guarded and a failure degrades to the same {ok: false, errors: [...]}
JSON contract every exit path here uses, never an unhandled traceback.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from git_state import (
    NotAWorkTreeError,
    detect_checkout_root,
    git,
    git_stdout,
    registered_worktree_paths,
    rev_exists,
    rev_parse,
    try_git_stdout,
)


def foreign_untracked_files(worktree: Path) -> list[str]:
    """Untracked, non-ignored files in worktree — see the identical check in
    land-work-create-preview.py's integration_worktree_unusable_reason().

    Nothing in this script's own lifecycle (reset --hard, --no-ff merges)
    ever creates an untracked file, so any present here means a person or
    another tool touched the shared worktree; it must not be silently reset
    over.
    """
    status = git_stdout("status", "--porcelain=v1", "--untracked-files=normal", cwd=worktree)
    return [line[3:] for line in status.splitlines() if line.startswith("??")]


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
    warnings: list[str] = []

    def emit(
        *,
        ok: bool,
        errors: list[str],
        base_sha: str | None = None,
        assembled: list[dict[str, object]] | None = None,
        evicted: list[dict[str, object]] | None = None,
        tip_sha: str | None = None,
        tip_tree: str | None = None,
    ) -> int:
        payload = {
            "cwd": str(cwd),
            "checkout_root": str(checkout_root),
            "worktree": str(worktree),
            "base_ref": args.base_ref,
            "base_sha": base_sha,
            "assembled": assembled or [],
            "evicted": evicted or [],
            "tip_sha": tip_sha,
            "tip_tree": tip_tree,
            "ok": ok,
            "warnings": warnings,
            "errors": errors,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if ok else 1

    try:
        registered = registered_worktree_paths(checkout_root)
        if worktree not in registered:
            errors.append(f"{worktree} is not a registered git worktree of {checkout_root}")
    except subprocess.CalledProcessError as exc:
        errors.append(
            f"unable to list registered worktrees of {checkout_root} "
            f"(`git worktree list` failed: {(exc.stderr or '').strip() or exc})"
        )

    if not rev_exists(args.base_ref, checkout_root):
        errors.append(f"base revision does not exist: {args.base_ref}")
    if not errors:
        try:
            foreign = foreign_untracked_files(worktree)
        except subprocess.CalledProcessError:
            errors.append(
                f"{worktree} is registered but `git status` failed in it "
                "(corrupted or partially removed worktree)"
            )
            foreign = []
        if foreign:
            errors.append(
                f"{worktree} has untracked files: {', '.join(foreign)}; "
                "refusing to reset over them"
            )

    if errors:
        return emit(ok=False, errors=errors)

    try:
        # base_ref was confirmed resolvable by rev_exists() above, but that is
        # a separate git call: a branch/tag base_ref can stop resolving
        # between the two calls (concurrent lease refresh, branch cleanup
        # sweep, another swarm agent). Survive that race the same way every
        # other git call below survives it.
        base_sha = rev_parse(args.base_ref, checkout_root)
    except subprocess.CalledProcessError as exc:
        return emit(
            ok=False,
            errors=[
                f"base revision {args.base_ref!r} stopped resolving before reset "
                f"(`git rev-parse` failed: {(exc.stderr or '').strip() or exc})"
            ],
        )

    try:
        # `reset --hard` clears any leftover merge state (including an
        # in-progress MERGE_HEAD) from a prior attempt, the same way
        # land-work-create-preview.py's persistent-worktree reuse path does.
        git("reset", "--hard", base_sha, cwd=worktree)
    except subprocess.CalledProcessError as exc:
        return emit(
            ok=False,
            errors=[f"`git reset --hard {base_sha}` failed in {worktree}: {(exc.stderr or '').strip() or exc}"],
            base_sha=base_sha,
        )

    assembled: list[dict[str, object]] = []
    evicted: list[dict[str, object]] = []
    current_head = base_sha

    for branch in args.branches:
        try:
            branch_sha = rev_parse(branch, checkout_root)
        except subprocess.CalledProcessError:
            # rev_exists + rev_parse is two separate git calls: a branch
            # deleted or renamed between them (e.g. a concurrent closure
            # sweep in this swarm/multi-agent context) must still evict
            # cleanly rather than crash mid-batch with no JSON output at all.
            evicted.append({"branch": branch, "reason": f"revision does not exist: {branch}", "conflicting_paths": []})
            continue

        merge_result = git("merge", "--no-ff", branch_sha, "-m", f"batch: merge {branch}", cwd=worktree, check=False)
        if merge_result.returncode == 0:
            post_merge_head = try_git_stdout("rev-parse", "HEAD", cwd=worktree)
            if post_merge_head is None:
                return emit(
                    ok=False,
                    errors=[f"`git rev-parse HEAD` failed in {worktree} after merging {branch!r}"],
                    base_sha=base_sha,
                    assembled=assembled,
                    evicted=evicted,
                )
            if post_merge_head == current_head:
                # `git merge --no-ff` exits 0 with no new commit ("Already up
                # to date.") when branch_sha is already an ancestor of HEAD --
                # a duplicate branch in the queue, or one transitively
                # contained via an earlier branch's own history. Recording
                # this as assembled with merge_commit_sha=HEAD would collide
                # with whichever branch's merge actually produced that
                # commit, misreporting a distinct merge that never happened.
                evicted.append(
                    {
                        "branch": branch,
                        "reason": "already up to date: no-op merge (duplicate or already-contained branch)",
                        "conflicting_paths": [],
                    }
                )
                continue
            current_head = post_merge_head
            assembled.append(
                {
                    "branch": branch,
                    "branch_sha": branch_sha,
                    "merge_commit_sha": current_head,
                }
            )
            continue

        conflicting_raw = try_git_stdout("diff", "--name-only", "--diff-filter=U", cwd=worktree)
        if conflicting_raw is None:
            return emit(
                ok=False,
                errors=[f"unable to list conflicting paths in {worktree} after merging {branch!r} failed"],
                base_sha=base_sha,
                assembled=assembled,
                evicted=evicted,
            )
        conflicting_paths = [line for line in conflicting_raw.splitlines() if line]
        git("merge", "--abort", cwd=worktree, check=False)
        reason = "conflict" if conflicting_paths else (merge_result.stderr.strip() or "merge failed")
        evicted.append({"branch": branch, "reason": reason, "conflicting_paths": conflicting_paths})

    tip_sha = try_git_stdout("rev-parse", "HEAD", cwd=worktree)
    tip_tree = try_git_stdout("rev-parse", "HEAD^{tree}", cwd=worktree) if tip_sha is not None else None
    if tip_sha is None or tip_tree is None:
        return emit(
            ok=False,
            errors=[f"unable to resolve the assembled tip in {worktree} after assembly finished"],
            base_sha=base_sha,
            assembled=assembled,
            evicted=evicted,
        )

    return emit(
        ok=True,
        errors=[],
        base_sha=base_sha,
        assembled=assembled,
        evicted=evicted,
        tip_sha=tip_sha,
        tip_tree=tip_tree,
    )


if __name__ == "__main__":
    try:
        exit_code = main()
    except NotAWorkTreeError as exc:
        json.dump(exc.diagnostic, sys.stdout, indent=2)
        sys.stdout.write("\n")
        exit_code = 1
    raise SystemExit(exit_code)
