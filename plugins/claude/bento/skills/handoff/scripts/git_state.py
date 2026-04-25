from __future__ import annotations

import subprocess
from pathlib import Path


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


def resolve_git_path(raw_path: str, cwd: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    return (cwd / path).resolve()


def detect_checkout_root(cwd: Path) -> Path:
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


def absolute_git_dir(cwd: Path) -> Path:
    return Path(git_stdout("rev-parse", "--absolute-git-dir", cwd=cwd)).resolve()


def common_git_dir(cwd: Path) -> Path:
    raw = git_stdout("rev-parse", "--git-common-dir", cwd=cwd)
    return resolve_git_path(raw, cwd)


def primary_checkout_root(cwd: Path) -> Path:
    return common_git_dir(cwd).parent.resolve()


def is_linked_worktree(cwd: Path) -> bool:
    return absolute_git_dir(cwd) != common_git_dir(cwd)


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
