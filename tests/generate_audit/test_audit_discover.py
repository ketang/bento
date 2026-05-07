import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/generate-audit/scripts/audit-discover.py"


def run(cmd: list[str], cwd: Path, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True, env=env)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class AuditDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Audit Discover Test")
        git(self.repo, "config", "user.email", "audit@example.com")
        write(self.repo / "README.md", "# Test Repo\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_helper(self, path_override: str | None = None) -> dict:
        env = None
        if path_override is not None:
            env = {**os.environ, "PATH": path_override}
        # Invoke via the current interpreter so PATH overrides do not break
        # shebang resolution of /usr/bin/env python3.
        result = run([sys.executable, str(SCRIPT)], self.repo, env=env)
        return json.loads(result.stdout)

    def test_discovers_typescript_repo_shape_and_workflow_surfaces(self) -> None:
        write(
            self.repo / "package.json",
            json.dumps(
                {
                    "packageManager": "pnpm@9.0.0",
                    "scripts": {
                        "build": "vite build",
                        "test": "vitest run",
                        "lint": "eslint .",
                        "typecheck": "tsc --noEmit",
                    },
                    "dependencies": {"react": "^18.0.0", "vite": "^5.0.0"},
                }
            ),
        )
        write(self.repo / "pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
        write(self.repo / "tsconfig.json", "{}\n")
        write(self.repo / "AGENTS.md", "Tracker: GitHub Issues\n")
        write(self.repo / "docs/ARCHITECTURE.md", "# Architecture\n")
        write(self.repo / ".github/workflows/ci.yml", "name: ci\n")
        write(self.repo / "schema.graphql", "type Query { hello: String! }\n")
        write(self.repo / "proto/service.proto", 'syntax = "proto3";\n')
        write(self.repo / ".env.example", "API_URL=\n")
        write(self.repo / "src/auth/service.ts", "export const auth = true;\n")
        write(self.repo / "jobs/worker.ts", "export const run = () => {};\n")
        write(self.repo / "db/migrations/001_init.sql", "create table test(id int);\n")
        write(self.repo / "scripts/release.sh", "#!/bin/sh\n")

        payload = self.run_helper()

        self.assertIn("TypeScript", payload["project_shape"]["languages"])
        self.assertIn("JavaScript", payload["project_shape"]["languages"])
        self.assertEqual(payload["project_shape"]["package_managers"], ["pnpm"])
        self.assertIn("pnpm run build", payload["project_shape"]["commands"]["build"])
        self.assertIn("pnpm run test", payload["project_shape"]["commands"]["test"])
        self.assertIn("pnpm run lint", payload["project_shape"]["commands"]["lint"])
        self.assertIn("pnpm run typecheck", payload["project_shape"]["commands"]["typecheck"])
        self.assertIn("README.md", payload["source_of_truth_docs"])
        self.assertIn("AGENTS.md", payload["source_of_truth_docs"])
        self.assertIn("docs/ARCHITECTURE.md", payload["source_of_truth_docs"])
        self.assertIn("docs/ARCHITECTURE.md", payload["documentation_analysis"]["design_docs"])
        self.assertIn("AGENTS.md", payload["documentation_analysis"]["agent_docs"])
        self.assertIn("schema.graphql", payload["interface_surfaces"]["api_schema_files"])
        self.assertIn("proto/service.proto", payload["interface_surfaces"]["api_schema_files"])
        self.assertIn(".env.example", payload["interface_surfaces"]["config_contract_files"])
        self.assertEqual(payload["workflow_surfaces"]["primary_branch"], "main")
        self.assertIn(".github/workflows/ci.yml", payload["workflow_surfaces"]["ci_workflows"])
        self.assertIn("scripts/release.sh", payload["workflow_surfaces"]["closeout_scripts"])
        self.assertIn("GitHub Issues", payload["workflow_surfaces"]["tracker_hints"])
        self.assertIn("src/auth/service.ts", payload["risk_surfaces"]["auth_permissions"])
        self.assertIn("jobs/worker.ts", payload["risk_surfaces"]["background_jobs"])
        self.assertIn("db/migrations/001_init.sql", payload["risk_surfaces"]["persistence_migrations"])

    def test_discovers_go_repo_and_make_targets(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")
        write(self.repo / "Makefile", "build:\n\t@echo build\nverify:\n\t@echo verify\nlint:\n\t@echo lint\n")

        payload = self.run_helper()

        self.assertIn("Go", payload["project_shape"]["languages"])
        self.assertIn("go.mod", payload["project_shape"]["manifests"])
        self.assertIn("Makefile", payload["project_shape"]["manifests"])
        self.assertIn("make build", payload["project_shape"]["commands"]["build"])
        self.assertIn("make verify", payload["project_shape"]["commands"]["test"])
        self.assertIn("make lint", payload["project_shape"]["commands"]["lint"])

    def test_extracts_documented_commands_and_matches_repo_commands(self) -> None:
        write(
            self.repo / "README.md",
            "\n".join(
                [
                    "# Test Repo",
                    "## Quickstart",
                    "```bash",
                    "npm run test",
                    "./scripts/bootstrap.sh",
                    "```",
                    "## Install",
                    "```bash",
                    "pip install -e .",
                    "```",
                ]
            )
            + "\n",
        )
        write(
            self.repo / "package.json",
            json.dumps({"scripts": {"test": "vitest run"}}),
        )
        write(self.repo / "scripts/bootstrap.sh", "#!/bin/sh\n")

        payload = self.run_helper()

        commands = payload["documentation_analysis"]["commands"]
        command_text = [entry["command"] for entry in commands]
        self.assertIn("npm run test", command_text)
        self.assertIn("./scripts/bootstrap.sh", command_text)
        self.assertIn("pip install -e .", command_text)

        test_entry = next(entry for entry in commands if entry["command"] == "npm run test")
        self.assertEqual(test_entry["category"], "test")
        self.assertEqual(test_entry["section"], "Quickstart")

        consistency = payload["documentation_analysis"]["command_consistency"]
        matched = {entry["command"]: entry for entry in consistency["matched_commands"]}
        unmatched = {entry["command"]: entry for entry in consistency["unmatched_commands"]}
        self.assertEqual(matched["npm run test"]["status"], "exact")
        self.assertEqual(matched["./scripts/bootstrap.sh"]["status"], "path_backed")
        self.assertEqual(unmatched["pip install -e ."]["status"], "unmatched")

    def test_detects_disabled_test_signals_across_code_and_ci(self) -> None:
        write(
            self.repo / "src/test_example.py",
            "\n".join(
                [
                    "import pytest",
                    "",
                    "@pytest.mark.skip(reason='flaky')",
                    "def test_example() -> None:",
                    "    pass",
                ]
            )
            + "\n",
        )
        write(
            self.repo / ".github/workflows/ci.yml",
            "\n".join(
                [
                    "jobs:",
                    "  test:",
                    "    if: false",
                    "    runs-on: ubuntu-latest",
                ]
            )
            + "\n",
        )
        write(
            self.repo / "README.md",
            "\n".join(
                [
                    "# Test Repo",
                    "TODO: re-enable tests after stabilization",
                ]
            )
            + "\n",
        )

        payload = self.run_helper()

        signals = payload["test_automation_health"]["disabled_signals"]
        signal_types = {(entry["path"], entry["signal"]) for entry in signals}
        self.assertIn(("src/test_example.py", "pytest_skip"), signal_types)
        self.assertIn((".github/workflows/ci.yml", "workflow_disabled"), signal_types)
        self.assertIn(("README.md", "re_enable_todo"), signal_types)

    def test_classifies_docs_for_design_contributor_and_install_utility_review(self) -> None:
        write(self.repo / "DESIGN.md", "# Design\nArchitecture and tradeoffs.\n")
        write(self.repo / "CONTRIBUTING.md", "# Contributing\nDevelopment workflow.\n")
        write(self.repo / "docs/installing.md", "# Installing\nQuickstart setup.\n")

        payload = self.run_helper()

        docs = payload["documentation_analysis"]
        self.assertIn("DESIGN.md", docs["design_docs"])
        self.assertIn("CONTRIBUTING.md", docs["contributor_docs"])
        self.assertIn("docs/installing.md", docs["install_quickstart_docs"])


    # ── Static analysis: Go ──────────────────────────────────────────────────

    def test_static_analysis_detects_golangci_lint(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")
        write(self.repo / ".golangci.yml", "linters:\n  enable-all: true\n")

        payload = self.run_helper()

        sa = payload["static_analysis"]
        tools = [t["tool"] for t in sa["applicable_tools"]]
        self.assertIn("golangci-lint", tools)
        entry = next(t for t in sa["applicable_tools"] if t["tool"] == "golangci-lint")
        self.assertEqual(entry["config"], ".golangci.yml")
        self.assertEqual(entry["run"], "golangci-lint run ./...")

    def test_static_analysis_zero_config_go_tools_always_detected(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")

        payload = self.run_helper()

        sa = payload["static_analysis"]
        tools = [t["tool"] for t in sa["applicable_tools"]]
        self.assertIn("govulncheck", tools)
        self.assertIn("gofmt", tools)

    def test_static_analysis_missing_by_language_go_without_linter(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")

        payload = self.run_helper()

        missing = payload["static_analysis"]["missing_by_language"]
        self.assertIn("Go", missing)
        self.assertIn("golangci-lint", missing["Go"])

    def test_static_analysis_go_linter_present_not_in_missing(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")
        write(self.repo / ".golangci.yml", "linters:\n  enable-all: true\n")

        payload = self.run_helper()

        missing = payload["static_analysis"]["missing_by_language"]
        go_missing = missing.get("Go", [])
        self.assertNotIn("golangci-lint", go_missing)

    # ── Static analysis: TypeScript ──────────────────────────────────────────

    def test_static_analysis_detects_eslint_in_typescript_repo(self) -> None:
        write(self.repo / "package.json", '{"dependencies": {}}')
        write(self.repo / "tsconfig.json", "{}")
        write(self.repo / ".eslintrc.json", '{"extends": "eslint:recommended"}')

        payload = self.run_helper()

        sa = payload["static_analysis"]
        tools = [t["tool"] for t in sa["applicable_tools"]]
        self.assertIn("eslint", tools)
        entry = next(t for t in sa["applicable_tools"] if t["tool"] == "eslint")
        self.assertIn("eslint", entry["run"])

    def test_static_analysis_detects_tsc_in_typescript_repo(self) -> None:
        write(self.repo / "package.json", '{"dependencies": {}}')
        write(self.repo / "tsconfig.json", "{}")

        payload = self.run_helper()

        tools = [t["tool"] for t in payload["static_analysis"]["applicable_tools"]]
        self.assertIn("tsc", tools)

    def test_static_analysis_missing_by_language_typescript_without_eslint(self) -> None:
        write(self.repo / "package.json", '{"dependencies": {}}')
        write(self.repo / "tsconfig.json", "{}")

        payload = self.run_helper()

        missing = payload["static_analysis"]["missing_by_language"]
        self.assertIn("TypeScript", missing)
        self.assertIn("eslint", missing["TypeScript"])

    # ── Static analysis: Python & Rust ───────────────────────────────────────

    def test_static_analysis_detects_ruff_in_python_repo(self) -> None:
        write(self.repo / "pyproject.toml", "[project]\nname = 'test'\n")
        write(self.repo / "ruff.toml", "[lint]\nselect = ['E', 'F']\n")

        payload = self.run_helper()

        tools = [t["tool"] for t in payload["static_analysis"]["applicable_tools"]]
        self.assertIn("ruff", tools)

    def test_static_analysis_missing_by_language_python_without_ruff(self) -> None:
        write(self.repo / "pyproject.toml", "[project]\nname = 'test'\n")

        payload = self.run_helper()

        missing = payload["static_analysis"]["missing_by_language"]
        self.assertIn("Python", missing)
        self.assertIn("ruff", missing["Python"])

    def test_static_analysis_zero_config_rust_tools_always_detected(self) -> None:
        write(self.repo / "Cargo.toml", "[package]\nname = 'test'\nversion = '0.1.0'\n")

        payload = self.run_helper()

        tools = [t["tool"] for t in payload["static_analysis"]["applicable_tools"]]
        self.assertIn("clippy", tools)
        self.assertIn("cargo-audit", tools)

    # ── Static analysis: installed vs applicable ────────────────────────────

    def test_installed_tools_excludes_tools_absent_from_path(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")

        # Locate the git binary so the helper can still init/inspect the repo,
        # then point PATH at a directory containing only that one symlink. No
        # audit tools (go, govulncheck, gocyclo, deadcode, ...) are reachable.
        git_path = shutil.which("git")
        self.assertIsNotNone(git_path, "git must be on PATH for this test")
        sandbox = Path(self.temp_dir.name) / "minimal-bin"
        sandbox.mkdir()
        os.symlink(git_path, sandbox / "git")
        payload = self.run_helper(path_override=str(sandbox))

        sa = payload["static_analysis"]
        applicable = [t["tool"] for t in sa["applicable_tools"]]
        installed = [t["tool"] for t in sa["installed_tools"]]
        self.assertIn("govulncheck", applicable)
        self.assertIn("gocyclo", applicable)
        self.assertIn("deadcode", applicable)
        for tool in ("govulncheck", "gocyclo", "deadcode"):
            self.assertNotIn(tool, installed)

    def test_installed_tools_subset_of_applicable_in_real_env(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")

        payload = self.run_helper()

        sa = payload["static_analysis"]
        applicable_keys = {(t["tool"], t.get("config")) for t in sa["applicable_tools"]}
        installed_keys = {(t["tool"], t.get("config")) for t in sa["installed_tools"]}
        self.assertTrue(installed_keys.issubset(applicable_keys))
        for entry in sa["installed_tools"]:
            self.assertIn("binary", entry)
            self.assertTrue(entry["binary"])

    # ── Static analysis: cross-language secrets ──────────────────────────────

    def test_static_analysis_detects_gitleaks_when_configured(self) -> None:
        write(self.repo / ".gitleaks.toml", "[extend]\nuseDefault = true\n")

        payload = self.run_helper()

        tools = [t["tool"] for t in payload["static_analysis"]["applicable_tools"]]
        self.assertIn("gitleaks", tools)

    def test_static_analysis_secrets_missing_cross_language_when_no_tool(self) -> None:
        payload = self.run_helper()

        missing_xl = payload["static_analysis"]["missing_cross_language"]
        self.assertIn("gitleaks", missing_xl)

    def test_static_analysis_secrets_not_missing_when_gitleaks_present(self) -> None:
        write(self.repo / ".gitleaks.toml", "[extend]\nuseDefault = true\n")

        payload = self.run_helper()

        missing_xl = payload["static_analysis"]["missing_cross_language"]
        self.assertNotIn("gitleaks", missing_xl)
        self.assertNotIn("trufflehog", missing_xl)
        self.assertNotIn("detect-secrets", missing_xl)

    # ── Static analysis: Go concurrency signals ──────────────────────────────

    def test_go_concurrency_signals_present_when_primitives_used(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")
        write(
            self.repo / "internal/server/server.go",
            "\n".join(
                [
                    "package server",
                    "",
                    "import (",
                    "\t\"sync\"",
                    "\t\"sync/atomic\"",
                    ")",
                    "",
                    "var mu sync.Mutex",
                    "var counter atomic.Int64",
                    "var done = make(chan struct{})",
                    "var once sync.Once",
                    "",
                    "func Run() {",
                    "\tgo func() { _ = 1 }()",
                    "}",
                ]
            )
            + "\n",
        )

        payload = self.run_helper()

        signals = payload["static_analysis"]["language_signals"]["Go"]["concurrency_signals"]
        self.assertNotEqual(signals, [])
        entry = next(
            (item for item in signals if item["path"] == "internal/server/server.go"),
            None,
        )
        self.assertIsNotNone(entry, f"expected an entry for internal/server/server.go in {signals!r}")
        detected = set(entry["signals"])
        self.assertEqual(
            detected,
            {"go_func", "sync_mutex", "channel", "sync_once", "sync_atomic"},
        )

    def test_go_concurrency_signals_empty_for_non_concurrent_go(self) -> None:
        write(self.repo / "go.mod", "module example.com/test\n\ngo 1.22\n")
        write(
            self.repo / "internal/util/util.go",
            "package util\n\nfunc Add(a, b int) int { return a + b }\n",
        )
        # Concurrency primitives in a *_test.go file must not count: race
        # detection guidance is driven by production code, not test setup.
        write(
            self.repo / "internal/util/util_test.go",
            "\n".join(
                [
                    "package util",
                    "",
                    "import \"sync\"",
                    "",
                    "var _ = sync.Mutex{}",
                ]
            )
            + "\n",
        )

        payload = self.run_helper()

        signals = payload["static_analysis"]["language_signals"]["Go"]["concurrency_signals"]
        self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()
