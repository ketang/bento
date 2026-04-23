#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from difflib import SequenceMatcher


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

DOC_SECTION_KEYWORDS = {
    "design_docs": ("design", "architecture", "adr", "decision", "system", "technical approach"),
    "code_adjacent_docs": ("api", "schema", "protocol", "migration", "interface", "model", "codegen"),
    "agent_docs": ("agent", "agents", "codex", "claude", "plugin", "skill", "prompt"),
    "contributor_docs": ("contributing", "development", "dev setup", "workflow", "maintainer"),
    "operations_docs": ("deploy", "release", "runbook", "operations", "incident", "oncall"),
    "install_quickstart_docs": ("install", "installation", "quickstart", "getting started", "setup"),
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

TEXT_FILE_SUFFIXES = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
}

DOC_COMMAND_LANGUAGES = {"bash", "sh", "shell", "zsh", "console", "shellscript"}

DISABLED_TEST_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("js_skip", re.compile(r"\b(?:it|test|describe)\.skip\s*\(")),
    ("js_todo", re.compile(r"\b(?:it|test)\.todo\s*\(")),
    ("pytest_skip", re.compile(r"@pytest\.mark\.(?:skip|skipif|xfail)\b|pytest\.mark\.(?:skip|skipif|xfail)\b")),
    ("unittest_skip", re.compile(r"@unittest\.skip\b|@skip\b|self\.skipTest\s*\(")),
    ("go_skip", re.compile(r"\bt\.Skipf?\s*\(")),
    ("junit_disabled", re.compile(r"@\s*Disabled\b")),
    ("rust_ignore", re.compile(r"#\[\s*ignore(?:\s*=.+?)?\s*\]")),
    ("workflow_disabled", re.compile(r"^\s*if:\s*(?:false|0)\s*$", re.MULTILINE)),
    ("skip_flag", re.compile(r"--skip(?:[-_ ]?tests?)\b|--no-?test\b|-DskipTests\b")),
    ("re_enable_todo", re.compile(r"(?:TODO|FIXME|HACK).{0,40}(?:re-?enable|restore).{0,40}test", re.IGNORECASE)),
]

# Each entry: (tool_name, language_or_None, config_candidates, run_command, zero_config)
# language=None  — cross-language tool, checked regardless of detected languages
# zero_config=True  — included whenever the language is present; never in missing_by_language
# zero_config=False — included only when a config file is found; in missing_by_language when absent
STATIC_TOOLS: list[tuple[str, str | None, list[str], str, bool]] = [
    # ── Go ──────────────────────────────────────────────────────────────────
    ("golangci-lint", "Go", [".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"],
     "golangci-lint run ./...", False),
    ("govulncheck",   "Go", [], "govulncheck ./...", True),
    ("gofmt",         "Go", [], "gofmt -l .", True),
    ("go-test-cover", "Go", [],
     "go test -coverprofile=coverage.out ./... && go tool cover -func=coverage.out", True),
    ("dupl",          "Go", [".dupl"], "dupl ./...", False),
    ("gocyclo",       "Go", [], "gocyclo -over 10 ./...", True),
    ("deadcode",      "Go", [], "deadcode ./...", True),
    ("nancy",         "Go", ["nancy.ignore"], "go list -json -deps ./... | nancy sleuth", False),
    # ── TypeScript / JavaScript ─────────────────────────────────────────────
    ("eslint", "TypeScript",
     [".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml",
      ".eslintrc.yaml", "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs"],
     "npx eslint . --format=compact", False),
    ("eslint", "JavaScript",
     [".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml",
      ".eslintrc.yaml", "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs"],
     "npx eslint . --format=compact", False),
    ("tsc",     "TypeScript", ["tsconfig.json"], "npx tsc --noEmit", False),
    ("knip",    "TypeScript", ["knip.json", "knip.ts", ".knip.json", "knip.jsonc"], "npx knip", False),
    ("knip",    "JavaScript", ["knip.json", "knip.ts", ".knip.json", "knip.jsonc"], "npx knip", False),
    ("prettier", "TypeScript",
     [".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.yml",
      ".prettierrc.yaml", "prettier.config.js", "prettier.config.cjs"],
     "npx prettier --check .", False),
    ("jscpd", "TypeScript", [".jscpd.json", ".jscpd.yaml", ".jscpd.yml"], "npx jscpd .", False),
    ("jscpd", "JavaScript", [".jscpd.json", ".jscpd.yaml", ".jscpd.yml"], "npx jscpd .", False),
    # ── Python ──────────────────────────────────────────────────────────────
    ("ruff",        "Python", ["ruff.toml", ".ruff.toml"], "ruff check .", False),
    ("mypy",        "Python", ["mypy.ini", ".mypy.ini"], "mypy .", False),
    ("bandit",      "Python", [".bandit", "bandit.yaml", "bandit.yml"], "bandit -r .", False),
    ("pytest-cov",  "Python", ["pytest.ini", "setup.cfg"], "pytest --cov", False),
    ("interrogate", "Python", [".interrogate.ini"], "interrogate .", False),
    ("vulture",     "Python", ["whitelist.py"], "vulture .", False),
    ("radon",       "Python", [], "radon cc . --min B -s", True),
    # ── Rust ────────────────────────────────────────────────────────────────
    ("clippy",                    "Rust", [], "cargo clippy -- -D warnings", True),
    ("clippy-cognitive-complexity","Rust", ["clippy.toml", ".clippy.toml"],
     "cargo clippy -- -W clippy::cognitive_complexity", False),
    ("cargo-audit",               "Rust", [], "cargo audit", True),
    ("rustfmt",                   "Rust", [".rustfmt.toml", "rustfmt.toml"], "cargo fmt --check", False),
    ("cargo-tarpaulin",           "Rust", [], "cargo tarpaulin", True),
    # ── Cross-language: secrets ─────────────────────────────────────────────
    ("gitleaks",       None, [".gitleaks.toml", ".gitleaks.json", ".gitleaksignore"],
     "gitleaks detect --source . --verbose", False),
    ("trufflehog",     None, [".trufflehog.yml", ".trufflehog.yaml"], "trufflehog filesystem .", False),
    ("detect-secrets", None, [".secrets.baseline"], "detect-secrets scan .", False),
    # ── Cross-language: config linting ──────────────────────────────────────
    ("hadolint",   None, [".hadolint.yaml", ".hadolint.yml"], "hadolint Dockerfile", False),
    ("yamllint",   None, [".yamllint", ".yamllint.yml", ".yamllint.yaml", ".yamllint.json"],
     "yamllint .", False),
    ("shellcheck", None, [],
     "find . -name '*.sh' -not -path './.git/*' | xargs shellcheck", True),
]

# Tools that form alternative groups: detecting any one covers the category.
# Used to suppress alternatives from missing_by_language once any in the group is found.
TOOL_ALTERNATIVE_GROUPS: dict[tuple[str | None, str], list[str]] = {
    ("Go",         "linter"):    ["golangci-lint"],
    ("TypeScript", "linter"):    ["eslint"],
    ("JavaScript", "linter"):    ["eslint"],
    ("Python",     "linter"):    ["ruff"],
    ("Rust",       "linter"):    ["clippy"],
    ("TypeScript", "dead_code"): ["knip"],
    ("JavaScript", "dead_code"): ["knip"],
    ("Python",     "type"):        ["mypy"],
    ("TypeScript", "type"):        ["tsc"],
    ("Go",         "duplication"):  ["dupl"],
    ("TypeScript", "duplication"):  ["jscpd"],
    ("JavaScript", "duplication"):  ["jscpd"],
    ("Rust",       "complexity"):   ["clippy-cognitive-complexity"],
    (None,         "secrets"):      ["gitleaks", "trufflehog", "detect-secrets"],
}


def is_doc_like(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in {".md", ".txt", ".rst"}


def is_text_like(path: str) -> bool:
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    return is_doc_like(path) or suffix in TEXT_FILE_SUFFIXES or name in {"Makefile", "Dockerfile", "Justfile"}


def read_text_if_reasonable(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="ignore")


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


def doc_bucket_for(path: str, content: str) -> set[str]:
    buckets: set[str] = set()
    lowered_path = path.lower()
    lowered_content = content.lower()

    for bucket, needles in DOC_SECTION_KEYWORDS.items():
        if any(needle in lowered_path or needle in lowered_content for needle in needles):
            buckets.add(bucket)

    if path == "AGENTS.md" or "/agents/" in lowered_path:
        buckets.add("agent_docs")
    if path == "CONTRIBUTING.md":
        buckets.add("contributor_docs")
    if Path(path).name in {"DESIGN.md", "ARCHITECTURE.md"}:
        buckets.add("design_docs")
    if "install" in lowered_path or "quickstart" in lowered_path or "getting-started" in lowered_path:
        buckets.add("install_quickstart_docs")

    return buckets


def classify_documentation(repo_root: Path, docs: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "design_docs": [],
        "code_adjacent_docs": [],
        "agent_docs": [],
        "contributor_docs": [],
        "operations_docs": [],
        "install_quickstart_docs": [],
    }

    for path in docs:
        content = read_text_if_reasonable(repo_root / path)
        if content is None:
            continue
        for bucket in doc_bucket_for(path, content):
            buckets[bucket].append(path)

    return {bucket: unique_sorted(paths) for bucket, paths in buckets.items()}


def heading_title(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    title = stripped.lstrip("#").strip()
    return title or None


def looks_like_shell_command(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if stripped.startswith(("$ ", "> ")):
        stripped = stripped[2:].strip()
    if len(stripped) < 3 or " " not in stripped:
        return bool(re.match(r"^[A-Za-z0-9_.:/-]+$", stripped))
    return bool(re.match(r"^[A-Za-z0-9_./:-]+(?:\s|$)", stripped))


def normalize_command(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith(("$ ", "> ")):
        stripped = stripped[2:].strip()
    return stripped


def command_category(command: str, section: str | None) -> str:
    lowered_command = command.lower()
    lowered = f"{section or ''} {command}".lower()
    if any(token in lowered_command for token in ("test", "pytest", "vitest", "jest", "go test", "cargo test", "unittest")):
        return "test"
    if any(token in lowered_command for token in ("lint", "ruff", "eslint", "shellcheck")):
        return "lint"
    if any(token in lowered_command for token in ("typecheck", "tsc", "mypy")):
        return "typecheck"
    if any(token in lowered_command for token in ("build", "compile")):
        return "build"
    if any(token in lowered_command for token in ("run", "serve", "start", "dev")):
        return "run"
    if any(token in lowered for token in ("install", "pip install", "npm install", "pnpm add", "brew install", "apt install")):
        return "install"
    if any(token in lowered for token in ("quickstart", "getting started", "setup", "bootstrap")):
        return "setup"
    return "other"


def extract_doc_commands(repo_root: Path, docs: list[str]) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    for path in docs:
        content = read_text_if_reasonable(repo_root / path)
        if content is None:
            continue

        current_heading: str | None = None
        in_fence = False
        fence_language = ""

        for line in content.splitlines():
            title = heading_title(line)
            if title:
                current_heading = title

            stripped = line.strip()
            if stripped.startswith("```"):
                if in_fence:
                    in_fence = False
                    fence_language = ""
                else:
                    in_fence = True
                    fence_language = stripped.removeprefix("```").strip().lower()
                continue

            if not in_fence:
                continue

            if fence_language and fence_language not in DOC_COMMAND_LANGUAGES:
                continue

            if not looks_like_shell_command(line):
                continue

            command = normalize_command(line)
            commands.append(
                {
                    "path": path,
                    "section": current_heading or "",
                    "category": command_category(command, current_heading),
                    "command": command,
                    "source": "fenced_block",
                }
            )

    unique_commands: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in commands:
        key = (entry["path"], entry["section"], entry["command"])
        if key in seen:
            continue
        seen.add(key)
        unique_commands.append(entry)
    return unique_commands


def shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def known_repo_commands(
    rel_files: list[str],
    project_commands: dict[str, list[str]],
    static_analysis: dict[str, object],
) -> list[str]:
    known = [
        command
        for commands in project_commands.values()
        for command in commands
    ]
    known.extend(
        entry["run"]
        for entry in static_analysis["detected_tools"]
        if isinstance(entry, dict) and isinstance(entry.get("run"), str)
    )
    known.extend(
        path
        for path in rel_files
        if path.startswith(("scripts/", "bin/", "hooks/")) and Path(path).suffix in {"", ".sh", ".py"}
    )
    return unique_sorted(known)


def best_command_match(command: str, known_commands: list[str], rel_files: list[str]) -> dict[str, str]:
    command_tokens = shell_tokens(command)
    first_token = command_tokens[0] if command_tokens else ""
    exact_match = command if command in known_commands else None
    if exact_match:
        return {"status": "exact", "match": exact_match}

    for known in known_commands:
        if command.startswith(known) or known.startswith(command):
            return {"status": "prefix", "match": known}

    for token in command_tokens:
        normalized = token.removeprefix("./")
        if normalized in rel_files:
            return {"status": "path_backed", "match": normalized}

    scored = [
        (SequenceMatcher(None, command, candidate).ratio(), candidate)
        for candidate in known_commands
    ]
    best_score, best_candidate = max(scored, default=(0.0, ""))
    if best_score >= 0.6:
        return {"status": "similar", "match": best_candidate}
    if first_token and any(Path(path).name == first_token for path in rel_files):
        return {"status": "entrypoint_name", "match": first_token}
    return {"status": "unmatched", "match": ""}


def evaluate_doc_commands(
    doc_commands: list[dict[str, str]],
    known_commands: list[str],
    rel_files: list[str],
) -> dict[str, list[dict[str, str]]]:
    matched: list[dict[str, str]] = []
    unmatched: list[dict[str, str]] = []
    for entry in doc_commands:
        result = best_command_match(entry["command"], known_commands, rel_files)
        evaluated = {**entry, **result}
        if result["status"] == "unmatched":
            unmatched.append(evaluated)
        else:
            matched.append(evaluated)
    return {"matched_commands": matched, "unmatched_commands": unmatched}


def disabled_test_signals(repo_root: Path, rel_files: list[str]) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    for path in rel_files:
        if not is_text_like(path):
            continue
        content = read_text_if_reasonable(repo_root / path)
        if content is None:
            continue
        for signal_type, pattern in DISABLED_TEST_PATTERNS:
            for match in pattern.finditer(content):
                line_number = content.count("\n", 0, match.start()) + 1
                line = content.splitlines()[line_number - 1].strip() if content.splitlines() else ""
                signals.append(
                    {
                        "path": path,
                        "line": str(line_number),
                        "signal": signal_type,
                        "excerpt": line[:200],
                    }
                )
    return signals


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


def detect_static_analysis_tools(
    repo_root: Path, file_set: set[str], languages: list[str]
) -> dict[str, object]:
    lang_set = set(languages)
    detected: list[dict[str, str | None]] = []
    detected_names: set[tuple[str | None, str]] = set()  # (language, tool_name)

    for tool_name, language, config_candidates, run_cmd, zero_config in STATIC_TOOLS:
        if language is not None and language not in lang_set:
            continue

        if zero_config:
            config_found: str | None = None
        else:
            config_found = next((c for c in config_candidates if c in file_set), None)
            if config_found is None:
                continue

        detected.append({"tool": tool_name, "config": config_found, "run": run_cmd})
        detected_names.add((language, tool_name))

    # Config-required tools absent for each detected language
    missing_by_language: dict[str, list[str]] = {}
    for tool_name, language, _configs, _run, zero_config in STATIC_TOOLS:
        if language is None or zero_config:
            continue
        if language not in lang_set:
            continue
        if (language, tool_name) in detected_names:
            continue
        covered = False
        for (grp_lang, _cat), alternatives in TOOL_ALTERNATIVE_GROUPS.items():
            if grp_lang == language and tool_name in alternatives:
                if any((language, alt) in detected_names for alt in alternatives):
                    covered = True
                    break
        if not covered:
            missing_by_language.setdefault(language, [])
            if tool_name not in missing_by_language[language]:
                missing_by_language[language].append(tool_name)

    # Config-required cross-language secrets tools not detected
    secrets_group = TOOL_ALTERNATIVE_GROUPS.get((None, "secrets"), [])
    secrets_detected = any((None, t) in detected_names for t in secrets_group)
    missing_cross_language: list[str] = []
    if not secrets_detected:
        missing_cross_language.append(secrets_group[0] if secrets_group else "gitleaks")

    return {
        "detected_tools": detected,
        "missing_by_language": missing_by_language,
        "missing_cross_language": missing_cross_language,
    }


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
    languages = detect_languages(file_set)
    static_analysis = detect_static_analysis_tools(repo_root, file_set, languages)
    doc_buckets = classify_documentation(repo_root, docs)
    project_commands = {
        "build": build_commands,
        "test": test_commands,
        "lint": lint_commands,
        "typecheck": typecheck_commands,
    }
    doc_commands = extract_doc_commands(repo_root, docs)
    repo_commands = known_repo_commands(rel_files, project_commands, static_analysis)
    doc_command_consistency = evaluate_doc_commands(doc_commands, repo_commands, rel_files)

    payload = {
        "repo_root": str(repo_root),
        "primary_branch": primary_branch,
        "project_shape": {
            "languages": languages,
            "frameworks": detect_frameworks(package_json),
            "package_managers": unique_sorted([manager] if manager else []),
            "manifests": unique_sorted(
                [
                    path
                    for path in rel_files
                    if Path(path).name in {"package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "Cargo.toml", "go.mod", "pyproject.toml", "Makefile"}
                ]
            ),
            "commands": project_commands,
        },
        "source_of_truth_docs": docs,
        "documentation_analysis": {
            **doc_buckets,
            "commands": doc_commands,
            "command_consistency": doc_command_consistency,
        },
        "interface_surfaces": interface_surfaces(rel_files),
        "workflow_surfaces": workflow_surfaces(repo_root, rel_files, docs, primary_branch),
        "risk_surfaces": detect_risk_surfaces(rel_files),
        "test_automation_health": {
            "disabled_signals": disabled_test_signals(repo_root, rel_files),
        },
        "static_analysis": static_analysis,
        "warnings": warnings,
    }

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
