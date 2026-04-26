#!/usr/bin/env python3
"""Strip launch-work log commits and the log file before merging.

Identifies commits in <base>..HEAD that touch only .launch-work/log.md, drops
them via a non-interactive `git rebase -i`, then commits the deletion of the
log file. Falls back to keeping the log-only commits when --keep-commits is
specified or when the rebase reports a conflict."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


LOG_REL_PATH = ".launch-work/log.md"


def _git(
    cwd: Path,
    *args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        env=full_env,
    )


def _list_commits(cwd: Path, base: str) -> list[str]:
    result = _git(cwd, "rev-list", "--reverse", f"{base}..HEAD")
    return [sha for sha in result.stdout.splitlines() if sha]


def _commit_paths(cwd: Path, sha: str) -> list[str]:
    result = _git(cwd, "show", "--name-only", "--format=", sha)
    return [line for line in result.stdout.splitlines() if line]


def classify(cwd: Path, base: str) -> tuple[list[str], list[str]]:
    log_only: list[str] = []
    work: list[str] = []
    for sha in _list_commits(cwd, base):
        paths = _commit_paths(cwd, sha)
        if paths and all(path == LOG_REL_PATH for path in paths):
            log_only.append(sha)
        else:
            work.append(sha)
    return log_only, work


_SEQUENCE_EDITOR_TEMPLATE = """#!/usr/bin/env python3
import sys

DROP = {drop_list!r}
todo_path = sys.argv[1]
with open(todo_path, encoding='utf-8') as fh:
    lines = fh.readlines()

out = []
for line in lines:
    parts = line.split()
    if (
        len(parts) >= 2
        and parts[0] == 'pick'
        and any(parts[1].startswith(sha[:7]) for sha in DROP)
    ):
        out.append('drop ' + ' '.join(parts[1:]) + '\\n')
    else:
        out.append(line)

with open(todo_path, 'w', encoding='utf-8') as fh:
    fh.writelines(out)
"""


def drop_via_rebase(cwd: Path, base: str, drop_shas: set[str]) -> bool:
    """Run a non-interactive rebase that drops the given shas. Return True on
    success, False on conflict (rebase aborted)."""
    if not drop_shas:
        return True
    editor_src = _SEQUENCE_EDITOR_TEMPLATE.format(drop_list=sorted(drop_shas))
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        editor_path = Path(f.name)
        f.write(editor_src)
    os.chmod(editor_path, 0o755)
    try:
        env = {"GIT_SEQUENCE_EDITOR": str(editor_path), "GIT_EDITOR": "true"}
        result = _git(cwd, "rebase", "-i", base, env=env, check=False)
        if result.returncode != 0:
            _git(cwd, "rebase", "--abort", check=False)
            return False
        return True
    finally:
        editor_path.unlink(missing_ok=True)


def remove_log_and_commit(cwd: Path) -> None:
    log_path = cwd / LOG_REL_PATH
    if log_path.exists():
        _git(cwd, "rm", LOG_REL_PATH)
        _git(cwd, "commit", "-m", "chore(launch-work-log): remove")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="land-work-clean-log")
    parser.add_argument("--base", required=True, help="base ref (typically the primary branch)")
    parser.add_argument("--apply", action="store_true", help="execute the cleanup")
    parser.add_argument(
        "--keep-commits",
        action="store_true",
        help="do not rewrite history; only commit the log deletion",
    )
    args = parser.parse_args(argv)

    cwd = Path.cwd().resolve()
    log_only, work = classify(cwd, args.base)
    payload: dict[str, object] = {
        "log_only_commits": log_only,
        "work_commits": len(work),
        "applied": False,
        "kept_log_commits": False,
        "rebase_conflict": False,
    }

    if not args.apply:
        print(json.dumps(payload, indent=2))
        return 0

    if args.keep_commits:
        payload["kept_log_commits"] = True
    else:
        ok = drop_via_rebase(cwd, args.base, set(log_only))
        if not ok:
            payload["rebase_conflict"] = True
            print(json.dumps(payload, indent=2))
            print(
                "land-work-clean-log: rebase conflict; rerun with --keep-commits "
                "to accept the log-only commits.",
                file=sys.stderr,
            )
            return 1

    remove_log_and_commit(cwd)
    payload["applied"] = True
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
