#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "target",
    ".venv",
    "venv",
    "__pycache__",
}

DOC_BASENAMES = {
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "DESIGN.md",
    "ARCHITECTURE.md",
    "docs.md",
}

TRACKER_HINTS = {
    "Beads": "Beads",
    "GitHub Issues": "GitHub Issues",
    "Jira": "Jira",
    "Linear": "Linear",
}

RISK_PATTERNS = {
    "auth_permissions": ("auth", "permission", "rbac", "acl", "oauth", "jwt"),
    "routers_validation": ("route", "router", "handler", "controller", "middleware", "validat", "schema"),
    "persistence_migrations": ("db", "database", "sql", "store", "repository", "repo", "migrat", "model"),
    "external_network": ("client", "http", "grpc", "graphql", "webhook", "fetch", "request"),
    "background_jobs": ("job", "worker", "queue", "cron", "scheduler", "task"),
    "secrets_tokens": ("secret", "token", "credential", "apikey", "api_key", "oauth", "jwt"),
}


def is_doc_like(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {".md", ".txt", ".rst"}


def git_stdout(*args: str, cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def detect_repo_root(cwd: Path) -> Path:
    repo_root = git_stdout("rev-parse", "--show-toplevel", cwd=cwd)
    return Path(repo_root).resolve() if repo_root else cwd.resolve()


def detect_primary_branch(repo_root: Path) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    origin_head = git_stdout("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", cwd=repo_root)
    if origin_head:
        return origin_head.removeprefix("origin/"), warnings

    warnings.append("origin/HEAD unavailable; primary branch detected from local refs")
    for candidate in ("main", "master"):
        local = git_stdout("show-ref", "--verify", f"refs/heads/{candidate}", cwd=repo_root)
        remote = git_stdout("show-ref", "--verify", f"refs/remotes/origin/{candidate}", cwd=repo_root)
        if local or remote:
            return candidate, warnings

    current = git_stdout("branch", "--show-current", cwd=repo_root)
    if current:
        warnings.append("fell back to the current branch because no primary branch ref was found")
        return current, warnings

    warnings.append("unable to detect primary branch")
    return None, warnings


def walk_repo(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        root_path = Path(current_root)
        for filename in sorted(filenames):
            files.append((root_path / filename).relative_to(repo_root))
    return files


def package_manager(repo_root: Path, files: set[str], package_json: dict | None) -> str | None:
    if package_json and isinstance(package_json.get("packageManager"), str):
        return str(package_json["packageManager"]).split("@", 1)[0]
    if "pnpm-lock.yaml" in files:
        return "pnpm"
    if "yarn.lock" in files:
        return "yarn"
    if "package-lock.json" in files:
        return "npm"
    return None


def npm_script_commands(package_json: dict | None, manager: str | None) -> dict[str, list[str]]:
    commands = {"build": [], "test": [], "lint": [], "typecheck": []}
    if not package_json:
        return commands

    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict):
        return commands

    manager_prefix = manager or "npm"

    categories = {
        "build": {"build", "compile"},
        "test": {"test", "test:unit", "test:integration", "check"},
        "lint": {"lint"},
        "typecheck": {"typecheck", "type-check"},
    }

    for category, keys in categories.items():
        for key in keys:
            if key in scripts:
                if manager_prefix == "npm":
                    commands[category].append(f"npm run {key}")
                else:
                    commands[category].append(f"{manager_prefix} run {key}")

    return commands


def make_commands(repo_root: Path) -> dict[str, list[str]]:
    commands = {"build": [], "test": [], "lint": [], "typecheck": []}
    makefile = repo_root / "Makefile"
    if not makefile.is_file():
        return commands

    for line in makefile.read_text(encoding="utf-8").splitlines():
        if ":" not in line or line.startswith("\t") or line.startswith("#"):
            continue
        target = line.split(":", 1)[0].strip()
        if not target or " " in target:
            continue
        lowered = target.lower()
        if "build" in lowered:
            commands["build"].append(f"make {target}")
        if "test" in lowered or lowered in {"check", "verify"}:
            commands["test"].append(f"make {target}")
        if "lint" in lowered:
            commands["lint"].append(f"make {target}")
        if "type" in lowered and "check" in lowered:
            commands["typecheck"].append(f"make {target}")

    return commands


def unique_sorted(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def read_json_if_present(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def detect_languages(files: set[str]) -> list[str]:
    languages: list[str] = []
    if "go.mod" in files:
        languages.append("Go")
    if "Cargo.toml" in files:
        languages.append("Rust")
    if "package.json" in files:
        languages.append("JavaScript")
    if "tsconfig.json" in files or any(path.endswith(".ts") or path.endswith(".tsx") for path in files):
        languages.append("TypeScript")
    if "pyproject.toml" in files or any(path.endswith(".py") for path in files):
        languages.append("Python")
    return unique_sorted(languages)


def detect_frameworks(package_json: dict | None) -> list[str]:
    if not package_json:
        return []
    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = package_json.get(key)
        if isinstance(value, dict):
            deps.update(value)

    frameworks = []
    for name in ("react", "vite", "mantine", "next", "express", "gql.tada", "graphql"):
        if name in deps:
            frameworks.append(name)
    return unique_sorted(frameworks)


def detect_docs(files: list[str]) -> list[str]:
    docs = []
    for path in files:
        if Path(path).name in DOC_BASENAMES:
            docs.append(path)
        elif path.startswith("docs/") and path.endswith(".md"):
            docs.append(path)
    return unique_sorted(docs)


def interface_surfaces(files: list[str]) -> dict[str, list[str]]:
    api_schema_files = []
    generated_code_paths = []
    config_contract_files = []
    cli_entrypoints = []

    for path in files:
        lowered = path.lower()
        if lowered.endswith((".graphql", ".gql", ".proto")) or "openapi" in lowered or "asyncapi" in lowered:
            api_schema_files.append(path)
        if "/generated/" in f"/{lowered}" or "/__generated__/" in f"/{lowered}" or ".gen." in lowered:
            generated_code_paths.append(path)
        if lowered.startswith(".env") or lowered.endswith(".env.example") or lowered.endswith(".env.sample"):
            config_contract_files.append(path)
        if lowered.endswith(("config.example.json", "config.example.yaml", "config.example.yml")):
            config_contract_files.append(path)
        if lowered.startswith("cmd/") or lowered.startswith("bin/") or lowered.startswith("scripts/"):
            cli_entrypoints.append(path)

    return {
        "api_schema_files": unique_sorted(api_schema_files),
        "generated_code_paths": unique_sorted(generated_code_paths),
        "config_contract_files": unique_sorted(config_contract_files),
        "cli_entrypoints": unique_sorted(cli_entrypoints),
    }


def tracker_hints(repo_root: Path, docs: list[str]) -> list[str]:
    hints = []
    for path in docs:
        content = (repo_root / path).read_text(encoding="utf-8", errors="ignore")
        for needle, label in TRACKER_HINTS.items():
            if needle in content:
                hints.append(label)
    return unique_sorted(hints)


def workflow_surfaces(repo_root: Path, files: list[str], docs: list[str], primary_branch: str | None) -> dict[str, object]:
    ci_workflows = [path for path in files if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))]
    task_runners = [path for path in files if Path(path).name in {"Makefile", "justfile", "Taskfile.yml", "Taskfile.yaml"}]
    closeout_scripts = [
        path
        for path in files
        if path.startswith("scripts/") and any(token in path.lower() for token in ("release", "deploy", "closeout", "land"))
    ]
    memory_files = [
        path
        for path in files
        if path in {"ERRORS.md", "knowledge/INDEX.md"} or path.startswith("knowledge/")
    ]

    return {
        "primary_branch": primary_branch,
        "ci_workflows": unique_sorted(ci_workflows),
        "task_runners": unique_sorted(task_runners),
        "closeout_scripts": unique_sorted(closeout_scripts),
        "memory_files": unique_sorted(memory_files),
        "tracker_hints": tracker_hints(repo_root, docs),
    }


def detect_risk_surfaces(files: list[str]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {key: [] for key in RISK_PATTERNS}
    for path in files:
        if is_doc_like(path):
            continue
        lowered = path.lower()
        for category, needles in RISK_PATTERNS.items():
            if any(needle in lowered for needle in needles):
                output[category].append(path)
    return {key: unique_sorted(value) for key, value in output.items()}


def main() -> int:
    cwd = Path.cwd().resolve()
    repo_root = detect_repo_root(cwd)
    primary_branch, warnings = detect_primary_branch(repo_root)
    rel_files = [str(path) for path in walk_repo(repo_root)]
    file_set = set(rel_files)

    package_json = read_json_if_present(repo_root / "package.json")
    manager = package_manager(repo_root, file_set, package_json)
    npm_commands = npm_script_commands(package_json, manager)
    makefile_commands = make_commands(repo_root)

    build_commands = unique_sorted(npm_commands["build"] + makefile_commands["build"])
    test_commands = unique_sorted(npm_commands["test"] + makefile_commands["test"])
    lint_commands = unique_sorted(npm_commands["lint"] + makefile_commands["lint"])
    typecheck_commands = unique_sorted(npm_commands["typecheck"] + makefile_commands["typecheck"])

    docs = detect_docs(rel_files)

    payload = {
        "repo_root": str(repo_root),
        "primary_branch": primary_branch,
        "project_shape": {
            "languages": detect_languages(file_set),
            "frameworks": detect_frameworks(package_json),
            "package_managers": unique_sorted([manager] if manager else []),
            "manifests": unique_sorted(
                [
                    path
                    for path in rel_files
                    if Path(path).name in {"package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "Cargo.toml", "go.mod", "pyproject.toml", "Makefile"}
                ]
            ),
            "commands": {
                "build": build_commands,
                "test": test_commands,
                "lint": lint_commands,
                "typecheck": typecheck_commands,
            },
        },
        "source_of_truth_docs": docs,
        "interface_surfaces": interface_surfaces(rel_files),
        "workflow_surfaces": workflow_surfaces(repo_root, rel_files, docs, primary_branch),
        "risk_surfaces": detect_risk_surfaces(rel_files),
        "warnings": warnings,
    }

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
