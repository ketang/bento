import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/build-vs-buy/scripts/build-vs-buy-discover.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class BuildVsBuyDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Build Vs Buy Test")
        git(self.repo, "config", "user.email", "build-vs-buy@example.com")
        write(self.repo / "README.md", "# Test Repo\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_helper(self, feature: str | None = None) -> dict:
        cmd = [str(SCRIPT)]
        if feature:
            cmd.extend(["--feature", feature])
        result = run(cmd, self.repo)
        return json.loads(result.stdout)

    def test_discovers_node_stack_constraints_and_existing_background_job_capability(self) -> None:
        write(
            self.repo / "package.json",
            json.dumps(
                {
                    "packageManager": "pnpm@9.0.0",
                    "dependencies": {
                        "next": "15.0.0",
                        "bullmq": "5.0.0",
                        "ioredis": "5.0.0",
                        "prisma": "5.0.0",
                        "@prisma/client": "5.0.0",
                        "stripe": "16.0.0",
                        "@sentry/nextjs": "8.0.0",
                        "@aws-sdk/client-s3": "3.0.0",
                    },
                }
            ),
        )
        write(self.repo / "pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
        write(self.repo / "vercel.json", "{}\n")
        write(self.repo / ".env.example", "AWS_REGION=us-east-1\nSTRIPE_SECRET_KEY=secret\nREDIS_URL=redis://localhost\n")
        write(self.repo / "docs/ARCHITECTURE.md", "Prefer existing stack. No new infra without approval.\n")
        write(self.repo / "prisma/schema.prisma", "generator client { provider = \"prisma-client-js\" }\n")
        write(self.repo / "prisma/migrations/001_init.sql", "create table example(id int);\n")
        write(self.repo / "src/api/webhooks/stripe.ts", "export const handler = async () => {};\n")
        write(self.repo / "workers/email-worker.ts", "export const worker = true;\n")

        payload = self.run_helper("add background jobs")

        self.assertIn("nextjs", payload["project_shape"]["frameworks"])
        self.assertEqual(payload["project_shape"]["package_managers"], ["pnpm"])
        self.assertIn("bullmq", payload["existing_capabilities"]["job_runtimes"])
        self.assertIn("redis", payload["existing_capabilities"]["key_value_and_cache"])
        self.assertIn("stripe", payload["existing_capabilities"]["payment_providers"])
        self.assertIn("sentry", payload["existing_capabilities"]["error_tracking"])
        self.assertIn("s3", payload["existing_capabilities"]["object_storage"])
        self.assertIn("aws", payload["existing_capabilities"]["cloud_providers"])
        self.assertIn("vercel", payload["existing_capabilities"]["hosting_platforms"])
        self.assertEqual(payload["constraints"]["cloud_bias"], "aws-preferred")
        self.assertIn("prefer-existing-stack", payload["constraints"]["stack_preferences"])
        self.assertIn("no-new-infra-without-approval", payload["constraints"]["stack_preferences"])
        self.assertIn("background_jobs", payload["derived_signals"]["feature_categories"])
        self.assertIn("background_jobs", payload["derived_signals"]["duplication_risk_in_category"])
        self.assertIn("retry_semantics", payload["derived_signals"]["recommended_comparison_categories"])
        self.assertIn("workers/email-worker.ts", payload["integration_surfaces"]["background_processing"])
        self.assertIn("src/api/webhooks/stripe.ts", payload["integration_surfaces"]["webhook_consumers"])

    def test_discovers_python_search_stack_and_self_hosted_policy(self) -> None:
        write(
            self.repo / "pyproject.toml",
            """
[project]
name = "example"
version = "0.1.0"
dependencies = [
  "fastapi>=0.110",
  "sqlalchemy>=2.0",
  "celery>=5.4",
  "redis>=5.0",
  "meilisearch>=0.30"
]
""".strip()
            + "\n",
        )
        write(self.repo / "docker-compose.yml", "services:\n  api:\n    image: test\n")
        write(self.repo / ".env.example", "MEILISEARCH_HOST=http://localhost:7700\nREDIS_URL=redis://localhost\n")
        write(self.repo / "docs/OPERATIONS.md", "Self-hosted preferred. GDPR applies. Avoid second tool per category.\n")
        write(self.repo / "alembic.ini", "[alembic]\nscript_location = alembic\n")
        write(self.repo / "alembic/versions/001_init.py", "revision = '001'\n")
        write(self.repo / "app/search/indexer.py", "def run() -> None:\n    pass\n")

        payload = self.run_helper("add search")

        self.assertIn("Python", payload["project_shape"]["languages"])
        self.assertIn("fastapi", payload["project_shape"]["frameworks"])
        self.assertIn("docker", payload["existing_capabilities"]["deployment_targets"])
        self.assertIn("celery", payload["existing_capabilities"]["job_runtimes"])
        self.assertIn("redis", payload["existing_capabilities"]["key_value_and_cache"])
        self.assertIn("meilisearch", payload["existing_capabilities"]["search_engines"])
        self.assertEqual(payload["constraints"]["hosting_bias"], "self-hosted-preferred")
        self.assertIn("gdpr", payload["constraints"]["compliance_hints"])
        self.assertIn("avoid-second-tool-in-category", payload["constraints"]["stack_preferences"])
        self.assertIn("search", payload["derived_signals"]["feature_categories"])
        self.assertIn("search", payload["derived_signals"]["duplication_risk_in_category"])
        self.assertIn("indexing_model", payload["derived_signals"]["recommended_comparison_categories"])
        self.assertIn("alembic/versions/001_init.py", payload["integration_surfaces"]["migrations"])
        self.assertNotIn(
            "Are hosted SaaS options acceptable, or should the comparison stay self-hosted?",
            payload["open_questions"],
        )

    def test_requests_feature_context_when_no_brief_is_provided(self) -> None:
        write(self.repo / "package.json", json.dumps({"dependencies": {"express": "5.0.0"}}))

        payload = self.run_helper()

        self.assertIn("What feature, subsystem, or capability is under consideration?", payload["open_questions"])
        self.assertIn("backend-api", payload["project_shape"]["service_types"])


if __name__ == "__main__":
    unittest.main()
