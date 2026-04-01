#!/usr/bin/env python3

import json
import sys
from pathlib import Path

from git_state import detect_checkout_root, detect_primary_branch, is_linked_worktree, primary_checkout_root


CONFIG_CANDIDATES = [
    Path(".claude/swarm-config.json"),
    Path(".codex/swarm-config.json"),
    Path("swarm-config.json"),
]


def load_config(repo_root: Path) -> tuple[Path | None, dict]:
    for relative in CONFIG_CANDIDATES:
        path = repo_root / relative
        if path.is_file():
            with path.open() as fh:
                return path, json.load(fh)
    return None, {}


def main() -> int:
    repo_root = detect_checkout_root(Path.cwd().resolve())
    integration_branch, warnings = detect_primary_branch(repo_root)
    config_path, config = load_config(repo_root)
    output = {
        "repo_root": str(repo_root),
        "primary_checkout_root": str(primary_checkout_root(repo_root)),
        "linked_worktree": is_linked_worktree(repo_root),
        "integration_branch": config.get("integration_branch") or integration_branch,
        "tracker": config.get("tracker"),
        "branch_naming": config.get("branch_naming"),
        "quality_gates": config.get("quality_gates"),
        "pre_completion": config.get("pre_completion"),
        "post_land_hooks": config.get("post_land_hooks"),
        "dependency_source": config.get("dependency_source"),
        "landing": config.get("landing"),
        "config_path": str(config_path) if config_path else None,
        "config_found": bool(config_path),
        "warnings": warnings,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
