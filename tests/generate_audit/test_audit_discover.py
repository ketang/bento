import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/generate-audit/scripts/audit-discover.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


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

    def run_helper(self) -> dict:
        result = run([str(SCRIPT)], self.repo)
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


if __name__ == "__main__":
    unittest.main()
