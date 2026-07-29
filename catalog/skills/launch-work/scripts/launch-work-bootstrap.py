#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from git_state import detect_checkout_root, detect_primary_branch, git, parse_worktrees, primary_checkout_root

UNTRACKED_ADVISORY_LIMIT = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True, help="target branch name")
    parser.add_argument("--worktree", required=True, help="target linked worktree path")
    parser.add_argument("--base-branch", help="branch to branch from; defaults to detected primary branch")
    parser.add_argument("--apply", action="store_true", help="create the branch and linked worktree")
    return parser.parse_args()


def untracked_advisories(root: Path) -> list[str]:
    """Untracked, non-ignored paths already present in the primary checkout."""
    result = git("status", "--porcelain", "--untracked-files=normal", cwd=root, check=False)
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if not line.startswith("?? "):
            continue
        entry = line[3:].strip()
        if entry.startswith('"') and entry.endswith('"'):
            entry = entry[1:-1]
        paths.append(entry)
    return paths


def is_ignored(root: Path, candidate: str) -> bool:
    return git("check-ignore", "-q", "--", candidate, cwd=root, check=False).returncode == 0


def is_tracked(root: Path, candidate: str) -> bool:
    result = git("ls-files", "--", candidate, cwd=root, check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def go_binary_names(root: Path) -> list[str]:
    names: list[str] = []
    go_mod = root / "go.mod"
    if go_mod.is_file():
        for line in go_mod.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("module "):
                module_path = line.removeprefix("module ").strip()
                if module_path:
                    names.append(module_path.rstrip("/").rsplit("/", 1)[-1])
                break
    cmd_dir = root / "cmd"
    if cmd_dir.is_dir():
        names.extend(sorted(child.name for child in cmd_dir.iterdir() if child.is_dir()))
    return list(dict.fromkeys(name for name in names if name and not name.startswith(".")))


def build_output_candidates(root: Path) -> list[tuple[str, str]]:
    """(path, reason) pairs of build outputs that a project of this type usually produces."""
    candidates: list[tuple[str, str]] = []

    if (root / "go.mod").is_file():
        for name in go_binary_names(root):
            candidates.append((name, "Go build output"))

    if (root / "package.json").is_file():
        candidates.append(("dist", "JavaScript/TypeScript build output"))

    if (root / "Cargo.toml").is_file():
        candidates.append(("target", "Rust build output"))

    if (root / "pyproject.toml").is_file() or (root / "setup.py").is_file():
        candidates.append(("__pycache__", "Python bytecode cache"))
        candidates.append(("dist", "Python build output"))

    deduped: dict[str, str] = {}
    for path, reason in candidates:
        deduped.setdefault(path, reason)
    return list(deduped.items())


def ignore_coverage_advisories(root: Path) -> list[str]:
    """Build-output paths this project type usually needs ignored but that .gitignore misses."""
    advisories: list[str] = []
    for candidate, reason in build_output_candidates(root):
        if is_ignored(root, candidate) or is_tracked(root, candidate):
            continue
        advisories.append(f"{candidate} ({reason}) is not covered by .gitignore")
    return advisories


def hygiene_advisories(root: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (untracked paths, ignore-coverage advisories, human-readable warnings)."""
    untracked = untracked_advisories(root)
    ignore_gaps = ignore_coverage_advisories(root)
    warnings: list[str] = []

    if untracked:
        shown = untracked[:UNTRACKED_ADVISORY_LIMIT]
        summary = ", ".join(shown)
        if len(untracked) > len(shown):
            summary += f", +{len(untracked) - len(shown)} more"
        warnings.append(
            f"primary checkout has {len(untracked)} untracked path(s) not covered by .gitignore: {summary}"
        )
    for gap in ignore_gaps:
        warnings.append(f"gitignore coverage: {gap}")

    return untracked, ignore_gaps, warnings


def evaluate(args: argparse.Namespace, cwd: Path) -> dict[str, object]:
    checkout_root = detect_checkout_root(cwd)
    primary_branch, warnings = detect_primary_branch(checkout_root)
    base_branch = args.base_branch or primary_branch
    target_worktree = Path(args.worktree).resolve()
    worktrees = parse_worktrees(checkout_root)
    branch_to_path = {
        str(worktree["branch"]): str(worktree["path"])
        for worktree in worktrees
        if worktree.get("branch")
    }

    errors: list[str] = []
    if git("show-ref", "--verify", f"refs/heads/{base_branch}", cwd=checkout_root, check=False).returncode != 0:
        errors.append(f"base branch does not exist locally: {base_branch}")
    if git("show-ref", "--verify", f"refs/heads/{args.branch}", cwd=checkout_root, check=False).returncode == 0:
        errors.append(f"target branch already exists locally: {args.branch}")
    if args.branch in branch_to_path:
        errors.append(f"target branch is already checked out in a worktree: {branch_to_path[args.branch]}")
    if target_worktree.exists():
        errors.append(f"target worktree path already exists: {target_worktree}")
    if str(target_worktree) in {str(worktree["path"]) for worktree in worktrees}:
        errors.append(f"target worktree path is already registered: {target_worktree}")

    primary_root = primary_checkout_root(checkout_root)
    untracked, ignore_gaps, hygiene_warnings = hygiene_advisories(primary_root)
    warnings = warnings + hygiene_warnings

    return {
        "checkout_root": str(checkout_root),
        "primary_checkout_root": str(primary_root),
        "primary_branch": primary_branch,
        "base_branch": base_branch,
        "target_branch": args.branch,
        "target_worktree": str(target_worktree),
        "existing_worktrees": worktrees,
        "existing_branch_worktrees": branch_to_path,
        "ok": not errors,
        "untracked_advisories": untracked,
        "ignore_coverage_advisories": ignore_gaps,
        "warnings": warnings,
        "errors": errors,
        "apply_mode": args.apply,
    }


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    result = evaluate(args, cwd)
    created = False

    if args.apply and not result["ok"]:
        json.dump({**result, "created": created}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    if args.apply:
        command = [
            "worktree",
            "add",
            "-b",
            str(result["target_branch"]),
            str(result["target_worktree"]),
            str(result["base_branch"]),
        ]
        exec_result = git(*command, cwd=Path(str(result["checkout_root"])), check=False)
        if exec_result.returncode != 0:
            payload = {
                **result,
                "created": created,
                "errors": list(result["errors"]) + [exec_result.stderr.strip() or "git worktree add failed"],
            }
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return exec_result.returncode
        created = True

    json.dump({**result, "created": created}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
