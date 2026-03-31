#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path


CONFIG_CANDIDATES = [
    Path(".claude/swarm-config.json"),
    Path(".codex/swarm-config.json"),
    Path("swarm-config.json"),
]


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def try_git(*args: str) -> str | None:
    try:
        return git(*args)
    except subprocess.CalledProcessError:
        return None


def detect_repo_root() -> Path:
    return Path(git("rev-parse", "--show-toplevel"))


def detect_integration_branch() -> str | None:
    origin_head = try_git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if origin_head:
        return origin_head.removeprefix("origin/")

    for candidate in ("main", "master"):
        if try_git("show-ref", "--verify", f"refs/heads/{candidate}") or try_git(
            "show-ref", "--verify", f"refs/remotes/origin/{candidate}"
        ):
            return candidate

    current = try_git("branch", "--show-current")
    return current or None


def load_config(repo_root: Path) -> tuple[Path | None, dict]:
    for relative in CONFIG_CANDIDATES:
        path = repo_root / relative
        if path.is_file():
            with path.open() as fh:
                return path, json.load(fh)
    return None, {}


def main() -> int:
    repo_root = detect_repo_root()
    config_path, config = load_config(repo_root)
    output = {
        "repo_root": str(repo_root),
        "integration_branch": config.get("integration_branch") or detect_integration_branch(),
        "tracker": config.get("tracker"),
        "branch_naming": config.get("branch_naming"),
        "quality_gates": config.get("quality_gates"),
        "pre_completion": config.get("pre_completion"),
        "post_land_hooks": config.get("post_land_hooks"),
        "dependency_source": config.get("dependency_source"),
        "landing": config.get("landing"),
        "config_path": str(config_path) if config_path else None,
        "config_found": bool(config_path),
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
