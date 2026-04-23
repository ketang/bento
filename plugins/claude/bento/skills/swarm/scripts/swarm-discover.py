#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from git_state import detect_checkout_root, detect_primary_branch, is_linked_worktree, primary_checkout_root


ROOT_CONFIG = Path("swarm-config.json")
RUNTIME_CONFIGS = {
    "claude": Path(".claude/swarm-config.json"),
    "codex": Path(".codex/swarm-config.json"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        choices=("auto", "claude", "codex"),
        default="auto",
        help="Select which runtime-specific swarm config to prefer.",
    )
    parser.add_argument(
        "--landing-target",
        help="Override the branch that swarm-managed work lands onto. Defaults to the config's integration_branch or the detected primary branch.",
    )
    return parser.parse_args()


def read_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_config(repo_root: Path, runtime: str) -> tuple[Path | None, dict, list[str]]:
    warnings: list[str] = []

    if runtime in RUNTIME_CONFIGS:
        for relative in (RUNTIME_CONFIGS[runtime], ROOT_CONFIG):
            path = repo_root / relative
            if path.is_file():
                return path, read_config(path), warnings
        return None, {}, warnings

    root_path = repo_root / ROOT_CONFIG
    if root_path.is_file():
        return root_path, read_config(root_path), warnings

    available_runtime_configs = [
        (name, repo_root / relative)
        for name, relative in RUNTIME_CONFIGS.items()
        if (repo_root / relative).is_file()
    ]
    if len(available_runtime_configs) == 1:
        _, path = available_runtime_configs[0]
        return path, read_config(path), warnings
    if len(available_runtime_configs) > 1:
        warnings.append(
            "multiple runtime-specific swarm configs found; rerun with --runtime claude or --runtime codex"
        )
    return None, {}, warnings


def main() -> int:
    args = parse_args()
    repo_root = detect_checkout_root(Path.cwd().resolve())
    integration_branch, warnings = detect_primary_branch(repo_root)
    config_path, config, config_warnings = load_config(repo_root, args.runtime)
    warnings.extend(config_warnings)
    output = {
        "runtime": args.runtime,
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
    landing_target = args.landing_target or output["integration_branch"]
    output["integration_branch"] = landing_target
    output["landing_target"] = landing_target
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
