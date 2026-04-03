#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


APPLY_DELETE_LOCAL_MERGED = "delete-local-merged-branches"


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def git_stdout(*args: str, cwd: Path) -> str:
    return git(*args, cwd=cwd).stdout.strip()


def try_git_stdout(*args: str, cwd: Path) -> str | None:
    result = git(*args, cwd=cwd, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def ref_exists(ref: str, cwd: Path) -> bool:
    return git("show-ref", "--verify", ref, cwd=cwd, check=False).returncode == 0


def detect_repo_root(cwd: Path) -> Path:
    return Path(git_stdout("rev-parse", "--show-toplevel", cwd=cwd)).resolve()


def detect_primary_branch(cwd: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    origin_head = try_git_stdout(
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        cwd=cwd,
    )
    if origin_head:
        return origin_head.removeprefix("origin/"), warnings

    warnings.append("origin/HEAD unavailable; primary branch detected from local refs")
    for candidate in ("main", "master"):
        if ref_exists(f"refs/heads/{candidate}", cwd) or ref_exists(
            f"refs/remotes/origin/{candidate}",
            cwd,
        ):
            return candidate, warnings

    current_branch = git_stdout("branch", "--show-current", cwd=cwd)
    if current_branch:
        warnings.append("fell back to the current branch because no primary branch ref was found")
        return current_branch, warnings

    raise RuntimeError("unable to detect primary branch")


def parse_worktrees(cwd: Path) -> list[dict[str, object]]:
    raw = git_stdout("worktree", "list", "--porcelain", cwd=cwd)
    worktrees: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in raw.splitlines():
        if not line:
            if current:
                worktrees.append(current)
                current = None
            continue

        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.removeprefix("worktree ")}
            continue

        if current is None:
            continue

        key, _, value = line.partition(" ")
        if key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "HEAD":
            current["head"] = value
        elif key == "detached":
            current["detached"] = True
        elif key == "locked":
            current["locked"] = value or True
        elif key == "prunable":
            current["prunable"] = value or True

    if current:
        worktrees.append(current)

    return worktrees


def local_branches(cwd: Path) -> list[str]:
    raw = git_stdout("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=cwd)
    return [line for line in raw.splitlines() if line]


def branch_merged_into_primary(branch: str, primary_branch: str, cwd: Path) -> bool:
    if branch == primary_branch:
        return True
    result = git("merge-base", "--is-ancestor", branch, primary_branch, cwd=cwd, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or f"merge-base failed for branch {branch}")
    return result.returncode == 0


def branch_unique_patch_count(branch: str, primary_branch: str, cwd: Path) -> int:
    if branch == primary_branch:
        return 0
    raw = git_stdout("cherry", primary_branch, branch, cwd=cwd)
    return sum(1 for line in raw.splitlines() if line.startswith("+"))


def ahead_behind(branch: str, primary_branch: str, cwd: Path) -> tuple[int, int]:
    raw = git_stdout("rev-list", "--left-right", "--count", f"{primary_branch}...{branch}", cwd=cwd)
    behind_str, ahead_str = raw.split()
    return int(behind_str), int(ahead_str)


def working_tree_entries(cwd: Path) -> list[dict[str, str]]:
    raw = git_stdout("status", "--porcelain=v1", "--untracked-files=all", cwd=cwd)
    entries: list[dict[str, str]] = []
    for line in raw.splitlines():
        path = line[3:] if len(line) > 2 and line[2] == " " else line[2:]
        entries.append(
            {
                "status": line[:2],
                "path": path,
                "raw": line,
            }
        )
    return entries


def stash_entries(cwd: Path) -> list[dict[str, str]]:
    raw = git_stdout("stash", "list", cwd=cwd)
    entries: list[dict[str, str]] = []
    for line in raw.splitlines():
        ref, _, summary = line.partition(":")
        entries.append({"ref": ref, "summary": summary.strip()})
    return entries


def classify_branches(
    branch_names: list[str],
    primary_branch: str,
    current_branch: str,
    checked_out_in_worktrees: set[str],
    cwd: Path,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []

    for branch in branch_names:
        merged_into_primary = branch_merged_into_primary(branch, primary_branch, cwd)
        unique_patch_count = branch_unique_patch_count(branch, primary_branch, cwd)
        behind_primary, ahead_primary = ahead_behind(branch, primary_branch, cwd)
        checked_out_elsewhere = branch in checked_out_in_worktrees
        current = branch == current_branch

        if branch == primary_branch:
            classification = "primary"
        elif current:
            classification = "review_required"
        elif checked_out_elsewhere:
            classification = "checked_out_in_worktree"
        elif merged_into_primary:
            classification = "safe_to_delete"
        elif unique_patch_count == 0:
            classification = "patch_equivalent_review"
        else:
            classification = "review_required"

        reasons: list[str] = []
        if merged_into_primary and branch != primary_branch:
            reasons.append("fully_merged_into_primary")
        if unique_patch_count == 0 and branch != primary_branch:
            reasons.append("no_unique_patches_vs_primary")
        if checked_out_elsewhere:
            reasons.append("checked_out_in_worktree")
        if current:
            reasons.append("current_branch")

        records.append(
            {
                "name": branch,
                "current": current,
                "checked_out_in_worktree": checked_out_elsewhere,
                "merged_into_primary": merged_into_primary,
                "unique_patch_count": unique_patch_count,
                "ahead_of_primary": ahead_primary,
                "behind_primary": behind_primary,
                "classification": classification,
                "reasons": reasons,
            }
        )

    return records


def build_summary(
    branches: list[dict[str, object]],
    worktrees: list[dict[str, object]],
    stashes: list[dict[str, str]],
    working_tree: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "safe_to_delete_local_branches": [
            branch["name"] for branch in branches if branch["classification"] == "safe_to_delete"
        ],
        "patch_equivalent_local_branches": [
            branch["name"]
            for branch in branches
            if branch["classification"] == "patch_equivalent_review"
        ],
        "checked_out_local_branches": [
            branch["name"]
            for branch in branches
            if branch["classification"] == "checked_out_in_worktree"
        ],
        "local_branches_requiring_review": [
            branch["name"] for branch in branches if branch["classification"] == "review_required"
        ],
        "worktree_count": len(worktrees),
        "stash_count": len(stashes),
        "working_tree_dirty": bool(working_tree),
    }


def apply_delete_local_merged_branches(
    branches: list[dict[str, object]],
    cwd: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for branch in branches:
        if branch["classification"] != "safe_to_delete":
            continue

        branch_name = str(branch["name"])
        result = git("branch", "-d", branch_name, cwd=cwd, check=False)
        if result.returncode == 0:
            applied.append({"action": "delete_local_branch", "branch": branch_name})
            continue

        skipped.append(
            {
                "action": "delete_local_branch",
                "branch": branch_name,
                "reason": result.stderr.strip() or "git branch -d failed",
            }
        )

    return applied, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        choices=[APPLY_DELETE_LOCAL_MERGED],
        help="apply the supported cleanup action after the dry-run scan",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        cwd = Path.cwd().resolve()
        repo_root = detect_repo_root(cwd)
        primary_branch, warnings = detect_primary_branch(repo_root)
        current_branch = git_stdout("branch", "--show-current", cwd=repo_root)
        worktrees = parse_worktrees(repo_root)
        checked_out_in_worktrees = {
            str(worktree["branch"])
            for worktree in worktrees
            if worktree.get("branch") and str(worktree["branch"]) != current_branch
        }
        branches = classify_branches(
            local_branches(repo_root),
            primary_branch,
            current_branch,
            checked_out_in_worktrees,
            repo_root,
        )
        working_tree = working_tree_entries(repo_root)
        stashes = stash_entries(repo_root)
        summary = build_summary(branches, worktrees, stashes, working_tree)
        applied_actions: list[dict[str, str]] = []
        skipped_actions: list[dict[str, str]] = []

        if args.apply == APPLY_DELETE_LOCAL_MERGED:
            applied_actions, skipped_actions = apply_delete_local_merged_branches(branches, repo_root)

        output = {
            "repo_root": str(repo_root),
            "primary_branch": primary_branch,
            "current_branch": current_branch,
            "worktrees": worktrees,
            "working_tree": working_tree,
            "stashes": stashes,
            "local_branches": branches,
            "summary": summary,
            "apply_mode": args.apply,
            "applied_actions": applied_actions,
            "skipped_actions": skipped_actions,
            "warnings": warnings,
        }
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
