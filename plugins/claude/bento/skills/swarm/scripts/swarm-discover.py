#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from git_state import detect_checkout_root, detect_primary_branch, is_linked_worktree, primary_checkout_root

SCRIPT_DIR = Path(__file__).resolve().parent
_LAUNCH_SCRIPTS = SCRIPT_DIR.parents[1] / "launch-work" / "scripts"
sys.path.insert(0, str(_LAUNCH_SCRIPTS))
import agent_plugins_resolver  # noqa: E402


ROOT_CONFIG = Path("swarm-config.json")
RUNTIME_CONFIGS = {
    "claude": Path(".claude/swarm-config.json"),
    "codex": Path(".codex/swarm-config.json"),
}
MARKETPLACE = "bento"
PLUGIN_NAME = "bento"
TEAMMATE_CONFIG_REL = Path("swarm") / "config.json"
BUNDLED_TEAMMATE_CONFIG = (
    Path(__file__).resolve().parent.parent / "references" / "config.json"
)


class TeammateConfigError(Exception):
    """Raised when Bento's swarm teammate configuration is invalid."""


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


LANDING_MODES = ("serial", "batch")
LANDING_DEFAULTS: dict = {
    "mode": "serial",
    "full_gate": None,
    "gate_scope": None,
    "batch_boundary_paths": [],
    "max_batch_size": 5,
    "linger_minutes": 5,
    "integration_worktree": None,
}


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _gate_scope_resolves(gate_scope: str, repo_root: Path) -> bool:
    try:
        tokens = shlex.split(gate_scope)
    except ValueError:
        return False
    if not tokens:
        return False
    command = tokens[0]
    if "/" in command or command.startswith("."):
        candidate = Path(command)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return shutil.which(command) is not None


def validate_landing_config(raw: object, repo_root: Path) -> tuple[dict | None, list[str]]:
    """Validate and normalize the swarm-config.json `landing` block.

    Fails safe: any problem that would let landing.mode: batch run without a
    real full-gate/gate-scope command degrades the whole block to serial
    full-gate behavior rather than silently weakening gating. Malformed
    values for the batching-tuning fields (batch_boundary_paths,
    max_batch_size, linger_minutes, integration_worktree) fall back to their
    documented defaults independently, since they do not affect gate
    strength.
    """
    warnings: list[str] = []
    if raw is None:
        return None, warnings
    if not isinstance(raw, dict):
        warnings.append(
            "swarm-discover: landing config must be an object; ignoring landing block"
        )
        return None, warnings

    result = dict(LANDING_DEFAULTS)

    mode = raw.get("mode", "serial")
    if mode not in LANDING_MODES:
        warnings.append(
            f"swarm-discover: invalid landing.mode {mode!r}; degrading to serial"
        )
        mode = "serial"
    result["mode"] = mode

    full_gate = raw.get("full_gate")
    if full_gate is not None and not _is_non_empty_string(full_gate):
        warnings.append(
            "swarm-discover: landing.full_gate must be a non-empty string; ignoring"
        )
        full_gate = None
    result["full_gate"] = full_gate

    gate_scope = raw.get("gate_scope")
    if gate_scope is not None and not _is_non_empty_string(gate_scope):
        warnings.append(
            "swarm-discover: landing.gate_scope must be a non-empty string; ignoring"
        )
        gate_scope = None
    gate_scope_resolves = gate_scope is not None and _gate_scope_resolves(
        gate_scope, repo_root
    )
    result["gate_scope"] = gate_scope

    if result["mode"] == "batch":
        problems = []
        if not full_gate:
            problems.append("landing.full_gate is required for landing.mode: batch")
        if gate_scope is None:
            problems.append("landing.gate_scope is required for landing.mode: batch")
        elif not gate_scope_resolves:
            problems.append(
                f"landing.gate_scope {gate_scope!r} does not resolve to an executable command"
            )
            gate_scope = None
        if problems:
            for problem in problems:
                warnings.append(f"swarm-discover: {problem}; degrading to serial")
            result["mode"] = "serial"
            result["gate_scope"] = gate_scope

    batch_boundary_paths = raw.get("batch_boundary_paths", [])
    if not (
        isinstance(batch_boundary_paths, list)
        and all(isinstance(item, str) for item in batch_boundary_paths)
    ):
        warnings.append(
            "swarm-discover: landing.batch_boundary_paths must be a list of strings; using []"
        )
        batch_boundary_paths = []
    result["batch_boundary_paths"] = batch_boundary_paths

    max_batch_size = raw.get("max_batch_size", 5)
    if not (
        isinstance(max_batch_size, int)
        and not isinstance(max_batch_size, bool)
        and max_batch_size > 0
    ):
        warnings.append(
            "swarm-discover: landing.max_batch_size must be a positive integer; using default 5"
        )
        max_batch_size = 5
    result["max_batch_size"] = max_batch_size

    linger_minutes = raw.get("linger_minutes", 5)
    if not (
        isinstance(linger_minutes, (int, float))
        and not isinstance(linger_minutes, bool)
        and linger_minutes >= 0
    ):
        warnings.append(
            "swarm-discover: landing.linger_minutes must be a non-negative number; using default 5"
        )
        linger_minutes = 5
    result["linger_minutes"] = linger_minutes

    integration_worktree = raw.get("integration_worktree")
    if integration_worktree is not None:
        if not _is_non_empty_string(integration_worktree):
            warnings.append(
                "swarm-discover: landing.integration_worktree must be a non-empty string; ignoring"
            )
            integration_worktree = None
        else:
            integration_worktree = str(Path(integration_worktree).expanduser())
    result["integration_worktree"] = integration_worktree

    return result, warnings


def resolve_teammate_config(repo_root: Path) -> Path:
    candidates = (
        repo_root / ".agent-plugins" / MARKETPLACE / PLUGIN_NAME / TEAMMATE_CONFIG_REL,
        agent_plugins_resolver.home_scope_base()
        / MARKETPLACE
        / PLUGIN_NAME
        / TEAMMATE_CONFIG_REL,
        BUNDLED_TEAMMATE_CONFIG,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    rendered_candidates = ", ".join(str(path) for path in candidates)
    raise TeammateConfigError(
        f"no swarm teammate config found at any candidate path: {rendered_candidates}"
    )


def optional_non_empty_string(config: dict, field: str, path: Path) -> str | None:
    if field not in config:
        return None
    value = config[field]
    if not isinstance(value, str) or not value.strip():
        raise TeammateConfigError(
            f"{path}: codex.{field} must be a non-empty string"
        )
    return value


def read_teammate_config(path: Path) -> tuple[str | None, str | None]:
    try:
        with path.open(encoding="utf-8") as fh:
            config = json.load(fh)
    except json.JSONDecodeError as exc:
        raise TeammateConfigError(
            f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise TeammateConfigError(f"{path}: unable to read config: {exc}") from exc

    if not isinstance(config, dict):
        raise TeammateConfigError(f"{path}: config root must be an object")
    codex_config = config.get("codex", {})
    if not isinstance(codex_config, dict):
        raise TeammateConfigError(f"{path}: codex must be an object")
    model = optional_non_empty_string(codex_config, "model", path)
    reasoning_effort = optional_non_empty_string(
        codex_config, "reasoning_effort", path
    )
    return model, reasoning_effort


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
    landing, landing_warnings = validate_landing_config(config.get("landing"), repo_root)
    warnings.extend(landing_warnings)
    teammate_model = None
    teammate_reasoning_effort = None
    teammate_config_path = None
    if args.runtime == "codex":
        try:
            resolved_teammate_config = resolve_teammate_config(repo_root)
            teammate_model, teammate_reasoning_effort = read_teammate_config(
                resolved_teammate_config
            )
            teammate_config_path = str(resolved_teammate_config)
        except TeammateConfigError as exc:
            print(f"swarm-discover: {exc}", file=sys.stderr)
            return 2
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
        "landing": landing,
        "teammate_model": teammate_model,
        "teammate_reasoning_effort": teammate_reasoning_effort,
        "teammate_config_path": teammate_config_path,
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
