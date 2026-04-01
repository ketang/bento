#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from build_vs_buy_catalog import (
    ENV_SIGNAL_PATTERNS,
    FAMILY_TO_TOOL_CATEGORIES,
    FEATURE_PATTERNS,
    FILE_SIGNAL_PATTERNS,
    FRAMEWORK_ALIASES,
    GENERAL_COMPARISON_CATEGORIES,
    POLICY_PATTERNS,
    TEXT_SIGNAL_PATTERNS,
    TOOL_CATEGORIES,
)


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

PLATFORM_FILES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "vercel.json",
    "netlify.toml",
    "render.yaml",
    "render.yml",
    "fly.toml",
    "wrangler.toml",
    "app.json",
    "Procfile",
    "serverless.yml",
    "serverless.yaml",
    "samconfig.toml",
    "template.yaml",
    "pnpm-workspace.yaml",
    "Makefile",
    "Vagrantfile",
}

MANIFEST_BASENAMES = {
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "bun.lock",
    "bun.lockb",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Pipfile.lock",
    "requirements.txt",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "Makefile",
}

TEXT_SCAN_SUFFIXES = {".md", ".txt", ".rst", ".yml", ".yaml", ".toml", ".json", ".tf", ".ini", ".env"}
MAX_TEXT_SCAN_BYTES = 256 * 1024
REQUIREMENT_NAME = re.compile(r"^[@A-Za-z0-9][@A-Za-z0-9._/-]*")
ENV_VAR = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*=", re.MULTILINE)


def unique_sorted(values: list[str] | set[str]) -> list[str]:
    return sorted({value for value in values if value})


def ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


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


def read_json_if_present(path: Path, warnings: list[str]) -> dict | None:
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        warnings.append(f"failed to parse JSON: {path} ({exc.msg})")
        return None


def read_toml_if_present(path: Path, warnings: list[str]) -> dict | None:
    if not path.is_file():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        warnings.append(f"failed to parse TOML: {path} ({exc})")
        return None


def normalize_dep_name(raw: str) -> str | None:
    value = raw.strip()
    if not value or value.startswith("#") or value.startswith("-r") or value.startswith("--"):
        return None

    lowered = value.lower().split(";", 1)[0].strip()
    if "#egg=" in lowered:
        lowered = lowered.split("#egg=", 1)[1]
    if "://" in lowered and "#egg=" not in value.lower():
        return None
    lowered = lowered.split("[", 1)[0]
    match = REQUIREMENT_NAME.match(lowered)
    if not match:
        return None
    name = match.group(0).rstrip(".")
    if name.startswith("@"):
        scope, _, package = name.partition("/")
        if not package:
            return None
        return f"{scope}/{package.replace('_', '-')}"
    return name.replace("_", "-")


def add_dependency(dep_evidence: dict[str, set[str]], raw_name: str, source: str) -> None:
    normalized = normalize_dep_name(raw_name)
    if normalized:
        dep_evidence.setdefault(normalized, set()).add(source)


def collect_package_json_dependencies(path: Path, rel_path: str, dep_evidence: dict[str, set[str]], warnings: list[str]) -> dict | None:
    data = read_json_if_present(path, warnings)
    if not data:
        return None
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = data.get(key)
        if isinstance(value, dict):
            for dep_name in value:
                add_dependency(dep_evidence, dep_name, f"{rel_path}:{key}:{dep_name}")
    return data


def collect_pyproject_dependencies(path: Path, rel_path: str, dep_evidence: dict[str, set[str]], warnings: list[str]) -> None:
    data = read_toml_if_present(path, warnings)
    if not data:
        return
    project = data.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            for dep in deps:
                if isinstance(dep, str):
                    add_dependency(dep_evidence, dep, f"{rel_path}:project.dependencies:{dep}")
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group, group_deps in optional.items():
                if isinstance(group_deps, list):
                    for dep in group_deps:
                        if isinstance(dep, str):
                            add_dependency(dep_evidence, dep, f"{rel_path}:project.optional-dependencies.{group}:{dep}")
    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            deps = poetry.get("dependencies")
            if isinstance(deps, dict):
                for dep_name in deps:
                    if dep_name.lower() != "python":
                        add_dependency(dep_evidence, dep_name, f"{rel_path}:tool.poetry.dependencies:{dep_name}")
            groups = poetry.get("group")
            if isinstance(groups, dict):
                for group_name, group_value in groups.items():
                    if isinstance(group_value, dict):
                        dependencies = group_value.get("dependencies")
                        if isinstance(dependencies, dict):
                            for dep_name in dependencies:
                                add_dependency(dep_evidence, dep_name, f"{rel_path}:tool.poetry.group.{group_name}:{dep_name}")


def collect_requirements_dependencies(path: Path, rel_path: str, dep_evidence: dict[str, set[str]]) -> None:
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        add_dependency(dep_evidence, line, f"{rel_path}:{line.strip()}")


def collect_cargo_dependencies(path: Path, rel_path: str, dep_evidence: dict[str, set[str]], warnings: list[str]) -> None:
    data = read_toml_if_present(path, warnings)
    if not data:
        return
    for section_name in ("dependencies", "dev-dependencies", "build-dependencies"):
        section = data.get(section_name)
        if isinstance(section, dict):
            for dep_name in section:
                add_dependency(dep_evidence, dep_name, f"{rel_path}:{section_name}:{dep_name}")
    workspace = data.get("workspace")
    if isinstance(workspace, dict):
        deps = workspace.get("dependencies")
        if isinstance(deps, dict):
            for dep_name in deps:
                add_dependency(dep_evidence, dep_name, f"{rel_path}:workspace.dependencies:{dep_name}")


def collect_go_mod_dependencies(path: Path, rel_path: str, dep_evidence: dict[str, set[str]]) -> None:
    in_require_block = False
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if line == "require (":
            in_require_block = True
            continue
        if in_require_block and line == ")":
            in_require_block = False
            continue
        if line.startswith("require "):
            module = line.split()[1]
            add_dependency(dep_evidence, module, f"{rel_path}:require:{module}")
            continue
        if in_require_block:
            module = line.split()[0]
            add_dependency(dep_evidence, module, f"{rel_path}:require:{module}")


def collect_dependencies(repo_root: Path, rel_files: list[str], warnings: list[str]) -> tuple[dict[str, set[str]], list[tuple[str, dict | None]]]:
    dep_evidence: dict[str, set[str]] = {}
    package_json_docs: list[tuple[str, dict | None]] = []
    for rel_path in rel_files:
        path = repo_root / rel_path
        name = Path(rel_path).name
        if name == "package.json":
            package_json_docs.append((rel_path, collect_package_json_dependencies(path, rel_path, dep_evidence, warnings)))
        elif name == "pyproject.toml":
            collect_pyproject_dependencies(path, rel_path, dep_evidence, warnings)
        elif "requirements" in name.lower() and name.endswith(".txt"):
            collect_requirements_dependencies(path, rel_path, dep_evidence)
        elif name == "Cargo.toml":
            collect_cargo_dependencies(path, rel_path, dep_evidence, warnings)
        elif name == "go.mod":
            collect_go_mod_dependencies(path, rel_path, dep_evidence)
    return dep_evidence, package_json_docs


def detect_package_managers(file_set: set[str], package_json_docs: list[tuple[str, dict | None]]) -> list[str]:
    managers: set[str] = set()
    for _, data in package_json_docs:
        if data and isinstance(data.get("packageManager"), str):
            managers.add(str(data["packageManager"]).split("@", 1)[0])
    if "pnpm-lock.yaml" in file_set:
        managers.add("pnpm")
    if "yarn.lock" in file_set:
        managers.add("yarn")
    if "package-lock.json" in file_set:
        managers.add("npm")
    if "bun.lock" in file_set or "bun.lockb" in file_set:
        managers.add("bun")
    if "poetry.lock" in file_set:
        managers.add("poetry")
    if "uv.lock" in file_set:
        managers.add("uv")
    if "Pipfile.lock" in file_set:
        managers.add("pipenv")
    if "pyproject.toml" in file_set and not managers.intersection({"poetry", "uv", "pipenv"}):
        managers.add("pip")
    if "Cargo.toml" in file_set or "Cargo.lock" in file_set:
        managers.add("cargo")
    if "go.mod" in file_set or "go.sum" in file_set:
        managers.add("go")
    return unique_sorted(managers)


def detect_languages(file_set: set[str]) -> list[str]:
    languages: set[str] = set()
    if "go.mod" in file_set or any(path.endswith(".go") for path in file_set):
        languages.add("Go")
    if "Cargo.toml" in file_set or any(path.endswith(".rs") for path in file_set):
        languages.add("Rust")
    if "package.json" in file_set:
        languages.add("JavaScript")
    if "tsconfig.json" in file_set or any(path.endswith(".ts") or path.endswith(".tsx") for path in file_set):
        languages.add("TypeScript")
    if "pyproject.toml" in file_set or any(path.endswith(".py") for path in file_set):
        languages.add("Python")
    if "Gemfile" in file_set or any(path.endswith(".rb") for path in file_set):
        languages.add("Ruby")
    if "composer.json" in file_set or any(path.endswith(".php") for path in file_set):
        languages.add("PHP")
    if "pom.xml" in file_set or any(path.endswith(".java") for path in file_set):
        languages.add("Java")
    if any(path.endswith(".kt") or path.endswith(".kts") for path in file_set):
        languages.add("Kotlin")
    if any(path.endswith(".csproj") or path.endswith(".cs") for path in file_set):
        languages.add("C#")
    return unique_sorted(languages)


def alias_matches(name: str, alias: str) -> bool:
    lowered_name = name.lower()
    lowered_alias = alias.lower()
    if lowered_alias.endswith("*"):
        return lowered_name.startswith(lowered_alias[:-1])
    return lowered_name == lowered_alias


def detect_frameworks(dep_evidence: dict[str, set[str]]) -> list[str]:
    frameworks: set[str] = set()
    for framework, aliases in FRAMEWORK_ALIASES.items():
        if any(any(alias_matches(dep, alias) for alias in aliases) for dep in dep_evidence):
            frameworks.add(framework)
    return unique_sorted(frameworks)


def detect_manifests(rel_files: list[str]) -> list[str]:
    manifests = []
    for rel_path in rel_files:
        name = Path(rel_path).name
        if name in MANIFEST_BASENAMES or rel_path.endswith(".csproj"):
            manifests.append(rel_path)
    return unique_sorted(manifests)


def detect_workspace_layout(file_set: set[str], package_json_docs: list[tuple[str, dict | None]]) -> str:
    manifest_dirs = {
        str(Path(path).parent)
        for path in file_set
        if Path(path).name in {"package.json", "pyproject.toml", "Cargo.toml", "go.mod"}
    }
    if "pnpm-workspace.yaml" in file_set:
        return "monorepo"
    if any(data and isinstance(data.get("workspaces"), (list, dict)) for _, data in package_json_docs):
        return "monorepo"
    if any(dir_path.startswith("apps") or dir_path.startswith("packages") for dir_path in manifest_dirs if dir_path != "."):
        return "monorepo"
    nested_dirs = {dir_path for dir_path in manifest_dirs if dir_path not in {".", ""}}
    if len(nested_dirs) > 1:
        return "multi-service"
    return "single-package"


def should_scan_text(rel_path: str) -> bool:
    path = Path(rel_path)
    name = path.name
    lowered = rel_path.lower()
    if name in DOC_BASENAMES:
        return True
    if lowered.startswith("docs/") and path.suffix.lower() in {".md", ".txt", ".rst"}:
        return True
    if lowered.startswith(".github/workflows/"):
        return True
    if name.startswith(".env"):
        return True
    if name in PLATFORM_FILES:
        return True
    if lowered.startswith(("infra/", "terraform/", "deploy/", "ops/", "k8s/", "helm/")) and path.suffix.lower() in TEXT_SCAN_SUFFIXES:
        return True
    return False


def collect_text_files(repo_root: Path, rel_files: list[str], warnings: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for rel_path in rel_files:
        if not should_scan_text(rel_path):
            continue
        path = repo_root / rel_path
        try:
            if path.stat().st_size > MAX_TEXT_SCAN_BYTES:
                warnings.append(f"skipped large text file: {rel_path}")
                continue
            output[rel_path] = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            warnings.append(f"failed to read text file: {rel_path} ({exc})")
    return output


def collect_env_var_evidence(text_files: dict[str, str]) -> dict[str, set[str]]:
    env_var_evidence: dict[str, set[str]] = {}
    for rel_path, content in text_files.items():
        if not Path(rel_path).name.startswith(".env"):
            continue
        for match in ENV_VAR.finditer(content):
            env_var_evidence.setdefault(match.group(1), set()).add(f"{rel_path}:{match.group(1)}")
    return env_var_evidence


def record_signal(signals: dict[str, set[str]], evidence: dict[str, dict[str, set[str]]], category: str, value: str, source: str) -> None:
    signals.setdefault(category, set()).add(value)
    evidence.setdefault(category, {}).setdefault(value, set()).add(source)


def detect_tool_signals(dep_evidence: dict[str, set[str]], rel_files: list[str], text_files: dict[str, str], env_var_evidence: dict[str, set[str]]) -> tuple[dict[str, set[str]], dict[str, dict[str, set[str]]]]:
    signals: dict[str, set[str]] = {}
    evidence: dict[str, dict[str, set[str]]] = {}

    for category, mapping in TOOL_CATEGORIES.items():
        for value, aliases in mapping.items():
            for dep_name, sources in dep_evidence.items():
                if any(alias_matches(dep_name, alias) for alias in aliases):
                    for source in sources:
                        record_signal(signals, evidence, category, value, source)

    for category, mapping in FILE_SIGNAL_PATTERNS.items():
        for value, needles in mapping.items():
            for rel_path in rel_files:
                lowered = rel_path.lower()
                if any(needle.lower() in lowered for needle in needles):
                    record_signal(signals, evidence, category, value, f"path:{rel_path}")

    for category, mapping in TEXT_SIGNAL_PATTERNS.items():
        for value, needles in mapping.items():
            for rel_path, content in text_files.items():
                lowered = content.lower()
                for needle in needles:
                    if needle.lower() in lowered:
                        record_signal(signals, evidence, category, value, f"text:{rel_path}:{needle}")

    for category, mapping in ENV_SIGNAL_PATTERNS.items():
        for value, prefixes in mapping.items():
            for env_var, sources in env_var_evidence.items():
                if any(env_var.startswith(prefix) for prefix in prefixes):
                    for source in sources:
                        record_signal(signals, evidence, category, value, f"env:{source}")

    return signals, evidence


def detect_api_protocols(rel_files: list[str], dep_evidence: dict[str, set[str]], frameworks: list[str]) -> list[str]:
    protocols: set[str] = set()
    for rel_path in rel_files:
        lowered = rel_path.lower()
        if lowered.endswith((".graphql", ".gql")):
            protocols.add("graphql")
        if lowered.endswith(".proto"):
            protocols.add("grpc")
        if "openapi" in lowered or "swagger" in lowered:
            protocols.add("rest")
        if "asyncapi" in lowered:
            protocols.add("asyncapi")
        if "webhook" in lowered:
            protocols.add("webhooks")
    if any("graphql" in dep or "gql.tada" in dep for dep in dep_evidence):
        protocols.add("graphql")
    if any(dep.startswith("@grpc/") or dep == "grpc" for dep in dep_evidence):
        protocols.add("grpc")
    backend_frameworks = {"express", "fastify", "nestjs", "django", "flask", "fastapi", "rails", "laravel", "spring-boot", "aspnet-core"}
    if protocols.intersection({"graphql", "grpc", "asyncapi"}) or set(frameworks).intersection(backend_frameworks):
        protocols.add("rest")
    return unique_sorted(protocols)


def detect_integration_surfaces(rel_files: list[str], dep_evidence: dict[str, set[str]], frameworks: list[str]) -> dict[str, list[str]]:
    schema_assets: list[str] = []
    env_contract_files: list[str] = []
    cli_entrypoints: list[str] = []
    background_processing: list[str] = []
    webhook_consumers: list[str] = []
    webhook_producers: list[str] = []
    migrations: list[str] = []

    for rel_path in rel_files:
        lowered = rel_path.lower()
        name = Path(rel_path).name.lower()
        if lowered.endswith((".graphql", ".gql", ".proto")) or "openapi" in lowered or "asyncapi" in lowered or lowered.endswith("schema.prisma"):
            schema_assets.append(rel_path)
        if name.startswith(".env") or lowered.endswith((".env.example", ".env.sample")) or lowered.endswith(("config.example.json", "config.example.yaml", "config.example.yml")):
            env_contract_files.append(rel_path)
        if lowered.startswith(("cmd/", "bin/", "scripts/")):
            cli_entrypoints.append(rel_path)
        if any(token in lowered for token in ("worker", "job", "queue", "cron", "scheduler", "celery")):
            background_processing.append(rel_path)
        if "webhook" in lowered:
            if any(token in lowered for token in ("client", "send", "dispatch", "publisher")):
                webhook_producers.append(rel_path)
            else:
                webhook_consumers.append(rel_path)
        if "migrat" in lowered or lowered.endswith("schema.prisma") or "alembic/versions" in lowered:
            migrations.append(rel_path)
            if rel_path not in schema_assets:
                schema_assets.append(rel_path)

    return {
        "api_protocols": detect_api_protocols(rel_files, dep_evidence, frameworks),
        "schema_assets": unique_sorted(schema_assets),
        "env_contract_files": unique_sorted(env_contract_files),
        "cli_entrypoints": unique_sorted(cli_entrypoints),
        "background_processing": unique_sorted(background_processing),
        "webhook_consumers": unique_sorted(webhook_consumers),
        "webhook_producers": unique_sorted(webhook_producers),
        "migrations": unique_sorted(migrations),
    }


def detect_service_types(frameworks: list[str], integration_surfaces: dict[str, list[str]], tool_signals: dict[str, set[str]], manifests: list[str]) -> list[str]:
    service_types: list[str] = []
    frontend_frameworks = {"react", "nextjs", "vite", "vue", "nuxt", "sveltekit"}
    backend_frameworks = {"express", "fastify", "nestjs", "django", "flask", "fastapi", "rails", "laravel", "spring-boot", "aspnet-core"}
    if set(frameworks).intersection(frontend_frameworks):
        service_types.append("frontend-web")
    if set(frameworks).intersection(backend_frameworks) or integration_surfaces["api_protocols"]:
        service_types.append("backend-api")
    if integration_surfaces["background_processing"] or any(tool_signals.get(key) for key in ("queues", "job_runtimes", "workflow_engines")):
        service_types.append("worker")
    if integration_surfaces["cli_entrypoints"]:
        service_types.append("cli")
    if "frontend-web" in service_types and "backend-api" in service_types:
        service_types.append("full-stack")
    if not service_types and manifests:
        service_types.append("library")
    return ordered_unique(service_types)


def doc_texts(text_files: dict[str, str]) -> dict[str, str]:
    return {
        path: content
        for path, content in text_files.items()
        if Path(path).name in DOC_BASENAMES or path.lower().startswith("docs/")
    }


def choose_priority(values: set[str], ordered: tuple[str, ...], fallback: str) -> str:
    for candidate in ordered:
        if candidate in values:
            return candidate
    return fallback


def vendor_terms() -> dict[str, set[str]]:
    terms: dict[str, set[str]] = {}
    for mapping in TOOL_CATEGORIES.values():
        for value, aliases in mapping.items():
            term_set = terms.setdefault(value, {value, value.replace("-", " ")})
            for alias in aliases:
                if "*" not in alias:
                    term_set.add(alias.lower())
    for mapping in FILE_SIGNAL_PATTERNS.values():
        for value in mapping:
            term_set = terms.setdefault(value, {value, value.replace("-", " ")})
            term_set.add(value.replace("-", " "))
    return terms


def detect_constraints(tool_signals: dict[str, set[str]], docs: dict[str, str], evidence: dict[str, dict[str, set[str]]]) -> dict[str, object]:
    detected_policy_sets: dict[str, set[str]] = {key: set() for key in POLICY_PATTERNS}
    preference_terms = vendor_terms()
    vendor_preferences: set[str] = set()
    vendor_bans: set[str] = set()

    for rel_path, content in docs.items():
        lowered = content.lower()
        for category, mapping in POLICY_PATTERNS.items():
            for value, needles in mapping.items():
                if any(needle in lowered for needle in needles):
                    detected_policy_sets[category].add(value)
                    evidence.setdefault(f"constraints.{category}", {}).setdefault(value, set()).add(f"doc:{rel_path}")
        for value, terms in preference_terms.items():
            if any(f"prefer {term}" in lowered or f"standardize on {term}" in lowered or f"default to {term}" in lowered for term in terms):
                vendor_preferences.add(value)
                evidence.setdefault("constraints.vendor_preferences", {}).setdefault(value, set()).add(f"doc:{rel_path}")
            if any(f"avoid {term}" in lowered or f"do not use {term}" in lowered or f"don't use {term}" in lowered or f"ban {term}" in lowered for term in terms):
                vendor_bans.add(value)
                evidence.setdefault("constraints.vendor_bans", {}).setdefault(value, set()).add(f"doc:{rel_path}")

    cloud_preferences = {value for value in vendor_preferences if value in {"aws", "gcp", "azure", "cloudflare", "digitalocean"}}
    if len(cloud_preferences) == 1:
        cloud_bias = f"{next(iter(cloud_preferences))}-preferred"
    elif len(tool_signals.get("cloud_providers", set())) == 1:
        cloud_bias = f"{next(iter(tool_signals['cloud_providers']))}-preferred"
    else:
        cloud_bias = "none-detected"

    return {
        "hosting_bias": choose_priority(
            detected_policy_sets["hosting_bias"],
            ("self-hosted-preferred", "managed-services-discouraged", "managed-services-allowed"),
            "unknown",
        ),
        "cloud_bias": cloud_bias,
        "license_constraints": unique_sorted(detected_policy_sets["license_constraints"]),
        "compliance_hints": unique_sorted(detected_policy_sets["compliance_hints"]),
        "stack_preferences": unique_sorted(detected_policy_sets["stack_preferences"]),
        "vendor_preferences": unique_sorted(vendor_preferences),
        "vendor_bans": unique_sorted(vendor_bans),
        "buy_vs_build_default": choose_priority(
            detected_policy_sets["buy_vs_build_default"],
            ("research-first", "build-first"),
            "unknown",
        ),
    }


def detect_feature_categories(feature_brief: str | None) -> list[str]:
    if not feature_brief:
        return []
    lowered = feature_brief.lower()
    categories = []
    for category, data in FEATURE_PATTERNS.items():
        if any(keyword in lowered for keyword in data["keywords"]):
            categories.append(category)
    return ordered_unique(categories)


def existing_capability_families(tool_signals: dict[str, set[str]]) -> list[str]:
    families = []
    for family, categories in FAMILY_TO_TOOL_CATEGORIES.items():
        if any(tool_signals.get(category) for category in categories):
            families.append(family)
    return ordered_unique(families)


def derive_signals(feature_brief: str | None, tool_signals: dict[str, set[str]], integration_surfaces: dict[str, list[str]], constraints: dict[str, object]) -> dict[str, object]:
    feature_categories = detect_feature_categories(feature_brief)
    incumbent_families = existing_capability_families(tool_signals)
    duplication_risk = ordered_unique([category for category in feature_categories if category in incumbent_families])
    comparison_categories = list(GENERAL_COMPARISON_CATEGORIES)
    integration_touchpoints: list[str] = []

    for category in feature_categories:
        feature_data = FEATURE_PATTERNS[category]
        comparison_categories.extend(feature_data["comparison_categories"])
        integration_touchpoints.extend(feature_data["touchpoints"])

    if integration_surfaces["migrations"]:
        integration_touchpoints.append("schema and migration workflow")
    if integration_surfaces["env_contract_files"]:
        integration_touchpoints.append("environment and credentials contract")
    if integration_surfaces["webhook_consumers"] or integration_surfaces["webhook_producers"]:
        integration_touchpoints.append("webhook ingestion and delivery")

    reuse_bias = duplication_risk[:]
    stack_preferences = constraints.get("stack_preferences")
    if isinstance(stack_preferences, list) and "prefer-existing-stack" in stack_preferences:
        for category in duplication_risk:
            if category not in reuse_bias:
                reuse_bias.append(category)

    return {
        "feature_categories": feature_categories,
        "existing_capability_in_category": incumbent_families,
        "duplication_risk_in_category": duplication_risk,
        "reuse_bias_by_category": ordered_unique(reuse_bias),
        "integration_touchpoints": ordered_unique(integration_touchpoints),
        "recommended_comparison_categories": ordered_unique(comparison_categories),
    }


def derive_open_questions(feature_brief: str | None, constraints: dict[str, object], derived_signals: dict[str, object]) -> list[str]:
    questions: list[str] = []
    if not feature_brief:
        questions.append("What feature, subsystem, or capability is under consideration?")
    if constraints["hosting_bias"] == "unknown":
        questions.append("Are hosted SaaS options acceptable, or should the comparison stay self-hosted?")
    if not constraints["license_constraints"]:
        questions.append("Are there license, procurement, or pricing constraints that rule out commercial or copyleft options?")
    if not constraints["compliance_hints"]:
        questions.append("Are there compliance, privacy, or data residency requirements that constrain vendor choice?")
    if constraints["cloud_bias"] != "none-detected":
        provider = str(constraints["cloud_bias"]).removesuffix("-preferred")
        questions.append(f"Should any new managed service stay within the current {provider} footprint?")

    for category in derived_signals["duplication_risk_in_category"]:
        human = category.replace("_", " ")
        questions.append(f"Should this extend the existing {human} stack instead of introducing a second tool in that category?")

    if feature_brief and not derived_signals["feature_categories"]:
        questions.append("Which existing capability family does this feature touch most directly?")

    return ordered_unique(questions)[:6]


def serialize_evidence(evidence: dict[str, dict[str, set[str]]]) -> dict[str, dict[str, list[str]]]:
    return {
        category: {value: sorted(sources) for value, sources in sorted(values.items())}
        for category, values in sorted(evidence.items())
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect deterministic build-vs-buy repo facts.")
    parser.add_argument("--feature", help="short feature brief used to tailor derived comparison signals")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cwd = Path.cwd().resolve()
    repo_root = detect_repo_root(cwd)
    primary_branch, warnings = detect_primary_branch(repo_root)
    rel_files = [str(path) for path in walk_repo(repo_root)]
    file_set = set(rel_files)

    dep_evidence, package_json_docs = collect_dependencies(repo_root, rel_files, warnings)
    frameworks = detect_frameworks(dep_evidence)
    manifests = detect_manifests(rel_files)
    package_managers = detect_package_managers(file_set, package_json_docs)
    text_files = collect_text_files(repo_root, rel_files, warnings)
    env_var_evidence = collect_env_var_evidence(text_files)
    tool_signals, evidence = detect_tool_signals(dep_evidence, rel_files, text_files, env_var_evidence)
    integration_surfaces = detect_integration_surfaces(rel_files, dep_evidence, frameworks)
    service_types = detect_service_types(frameworks, integration_surfaces, tool_signals, manifests)
    constraints = detect_constraints(tool_signals, doc_texts(text_files), evidence)
    derived_signals = derive_signals(args.feature, tool_signals, integration_surfaces, constraints)
    open_questions = derive_open_questions(args.feature, constraints, derived_signals)

    payload = {
        "repo_root": str(repo_root),
        "primary_branch": primary_branch,
        "feature_brief": args.feature,
        "project_shape": {
            "languages": detect_languages(file_set),
            "package_managers": package_managers,
            "frameworks": frameworks,
            "workspace_layout": detect_workspace_layout(file_set, package_json_docs),
            "service_types": service_types,
            "manifests": manifests,
        },
        "existing_capabilities": {category: unique_sorted(values) for category, values in sorted(tool_signals.items())},
        "integration_surfaces": integration_surfaces,
        "constraints": constraints,
        "derived_signals": derived_signals,
        "evidence": serialize_evidence(evidence),
        "open_questions": open_questions,
        "warnings": warnings,
    }

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
