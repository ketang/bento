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


def rev_exists(rev: str, cwd: Path) -> bool:
    return git("rev-parse", "--verify", f"{rev}^{{commit}}", cwd=cwd, check=False).returncode == 0


def resolve_git_path(raw_path: str, cwd: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    return (cwd / path).resolve()


class NotAWorkTreeError(RuntimeError):
    """Raised when git cannot resolve a work tree root for cwd: a bare
    checkout (core.bare=true, typically with orphaned working-tree files
    left behind), a location literally inside a .git directory, or a
    directory that is not a git repository at all. Carries a ready-to-emit
    diagnostic so every caller reports this the same way instead of leaking
    an uncaught CalledProcessError traceback with no next step (bento-
    rdtn.13)."""

    def __init__(self, diagnostic: dict):
        super().__init__(diagnostic.get("detail") or "not a work tree")
        self.diagnostic = diagnostic


def is_bare_repository(cwd: Path) -> bool:
    return try_git_stdout("rev-parse", "--is-bare-repository", cwd=cwd) == "true"


def _not_a_work_tree_diagnostic(cwd: Path, detail: str) -> dict:
    is_bare = is_bare_repository(cwd)
    is_inside_git_dir = try_git_stdout("rev-parse", "--is-inside-git-dir", cwd=cwd) == "true"
    is_git_repository = git("rev-parse", "--git-dir", cwd=cwd, check=False).returncode == 0
    return {
        "error": "not_a_work_tree",
        "detail": detail,
        "hint": "git config --get core.bare; unset core.bare or run from a linked worktree",
        "is_bare_repository": is_bare,
        "is_inside_git_dir": is_inside_git_dir,
        "is_git_repository": is_git_repository,
    }


def detect_checkout_root(cwd: Path) -> Path:
    result = git("rev-parse", "--show-toplevel", cwd=cwd, check=False)
    if result.returncode != 0:
        raise NotAWorkTreeError(_not_a_work_tree_diagnostic(cwd, result.stderr.strip()))
    return Path(result.stdout.strip()).resolve()


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


def ahead_behind(base_ref: str, head_ref: str, cwd: Path) -> tuple[int, int]:
    raw = git_stdout("rev-list", "--left-right", "--count", f"{base_ref}...{head_ref}", cwd=cwd)
    behind_str, ahead_str = raw.split()
    return int(behind_str), int(ahead_str)


def working_tree_dirty(cwd: Path) -> bool:
    return bool(git_stdout("status", "--porcelain=v1", "--untracked-files=all", cwd=cwd))


def registered_worktree_paths(cwd: Path) -> set[Path]:
    raw = git_stdout("worktree", "list", "--porcelain", cwd=cwd)
    paths: set[Path] = set()
    for line in raw.splitlines():
        if line.startswith("worktree "):
            paths.add(Path(line[len("worktree ") :]).resolve())
    return paths


def current_branch(cwd: Path) -> str:
    return git_stdout("branch", "--show-current", cwd=cwd)


def rev_parse(ref: str, cwd: Path) -> str:
    return git_stdout("rev-parse", ref, cwd=cwd)


def tree_for_ref(ref: str, cwd: Path) -> str:
    return git_stdout("rev-parse", f"{ref}^{{tree}}", cwd=cwd)
