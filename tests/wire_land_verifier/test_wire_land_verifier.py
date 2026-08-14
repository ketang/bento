import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, run, write


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/wire-land-verifier/scripts/wire-land-verifier.py"

MANIFEST_REL = ".agent-plugins/bento/bento/land-work/verifier.json"


class WireLandVerifierTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Wire Test")
        git(self.repo, "config", "user.email", "wire@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def wire(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(SCRIPT), *args], self.repo, check=check)

    def payload(self, result: subprocess.CompletedProcess[str]) -> dict:
        return json.loads(result.stdout)

    def passing_check(self) -> str:
        """A repo-local script that behaves like a real (passing) gate command."""
        gate = self.repo / "gate.sh"
        write(gate, "#!/bin/sh\necho running gate\nexit 0\n")
        gate.chmod(0o755)
        return "unit tests::./gate.sh"

    def failing_check(self) -> str:
        gate = self.repo / "redgate.sh"
        write(gate, "#!/bin/sh\necho broken\nexit 3\n")
        gate.chmod(0o755)
        return "unit tests::./redgate.sh"


class DiscoverTest(WireLandVerifierTestBase):
    def test_ranks_aggregate_make_targets_above_narrow_ones(self) -> None:
        write(self.repo / "Makefile", "fmt:\n\techo fmt\n\nci:\n\techo ci\n")
        payload = self.payload(self.wire("discover"))
        commands = [c["command"] for c in payload["candidates"]]
        self.assertIn("make ci", commands)
        self.assertIn("make fmt", commands)
        self.assertLess(commands.index("make ci"), commands.index("make fmt"))

    def test_reads_package_json_scripts_and_justfile(self) -> None:
        write(
            self.repo / "package.json",
            json.dumps({"scripts": {"test": "vitest run", "dev": "vite"}}),
        )
        write(self.repo / "justfile", "check:\n    echo hi\n")
        payload = self.payload(self.wire("discover"))
        commands = [c["command"] for c in payload["candidates"]]
        self.assertIn("npm run test", commands)
        self.assertIn("just check", commands)

    def test_reads_github_workflow_run_steps(self) -> None:
        write(
            self.repo / ".github/workflows/ci.yml",
            "jobs:\n  build:\n    steps:\n      - run: pytest -q\n",
        )
        payload = self.payload(self.wire("discover"))
        commands = [c["command"] for c in payload["candidates"]]
        self.assertIn("pytest -q", commands)

    def test_discover_never_writes_anything(self) -> None:
        write(self.repo / "Makefile", "ci:\n\techo ci\n")
        before = git(self.repo, "status", "--porcelain").stdout
        self.wire("discover")
        self.assertFalse((self.repo / MANIFEST_REL).exists())
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, before)

    def test_empty_repo_reports_no_candidates_without_failing(self) -> None:
        payload = self.payload(self.wire("discover"))
        self.assertEqual(payload["candidates"], [])


class DraftTest(WireLandVerifierTestBase):
    def test_draft_stages_files_without_installing_them(self) -> None:
        payload = self.payload(self.wire("draft", "--check", self.passing_check()))
        self.assertFalse((self.repo / MANIFEST_REL).exists())
        self.assertFalse((self.repo / "scripts/land-work-verifier.py").exists())
        self.assertIn("wrapper_body", payload)
        self.assertIn("manifest_body", payload)
        manifest = json.loads(payload["manifest_body"])
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["verified_noop"], [])
        self.assertEqual(manifest["command"], ["./scripts/land-work-verifier.py"])

    def test_draft_requires_at_least_one_check(self) -> None:
        result = self.wire("draft", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_draft_rejects_no_op_commands(self) -> None:
        for command in ("true", ":", "echo ok", "exit 0"):
            with self.subTest(command=command):
                result = self.wire("draft", "--check", f"gate::{command}", check=False)
                self.assertNotEqual(result.returncode, 0, command)
                self.assertIn("no-op", (result.stderr + result.stdout).lower())

    def test_draft_rejects_unresolvable_executable(self) -> None:
        result = self.wire(
            "draft", "--check", "gate::./definitely-not-here.sh", check=False
        )
        self.assertNotEqual(result.returncode, 0)

    def test_draft_accepts_bare_command_as_its_own_name(self) -> None:
        gate = self.repo / "gate.sh"
        write(gate, "#!/bin/sh\nexit 0\n")
        gate.chmod(0o755)
        payload = self.payload(self.wire("draft", "--check", "./gate.sh"))
        self.assertEqual([c["name"] for c in payload["checks"]], ["./gate.sh"])

    def test_custom_wrapper_path_is_reflected_in_manifest(self) -> None:
        payload = self.payload(
            self.wire(
                "draft",
                "--check",
                self.passing_check(),
                "--wrapper-path",
                "tools/verify.py",
            )
        )
        manifest = json.loads(payload["manifest_body"])
        self.assertEqual(manifest["command"], ["./tools/verify.py"])


class ValidateTest(WireLandVerifierTestBase):
    def test_validate_runs_the_staged_wrapper_and_reports_schema_valid_output(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        payload = self.payload(self.wire("validate"))
        self.assertTrue(payload["schema_valid"])
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["selected_check_count"], 1)

    def test_validate_reports_failed_status_for_a_red_gate_but_stays_schema_valid(self) -> None:
        self.wire("draft", "--check", self.failing_check())
        result = self.wire("validate", check=False)
        payload = self.payload(result)
        self.assertTrue(payload["schema_valid"])
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["selected_check_count"], 1)

    def test_validate_requires_a_draft(self) -> None:
        result = self.wire("validate", check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_validate_does_not_install_anything(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        self.assertFalse((self.repo / MANIFEST_REL).exists())


class ApplyTest(WireLandVerifierTestBase):
    def test_apply_installs_wrapper_and_manifest_after_validation(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        payload = self.payload(self.wire("apply"))
        manifest_path = self.repo / MANIFEST_REL
        wrapper_path = self.repo / "scripts/land-work-verifier.py"
        self.assertTrue(manifest_path.exists())
        self.assertTrue(wrapper_path.exists())
        self.assertTrue(wrapper_path.stat().st_mode & 0o111)
        self.assertEqual(json.loads(manifest_path.read_text())["schema_version"], 1)
        self.assertTrue(payload["applied"])

    def test_apply_refuses_without_a_validation_receipt(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / MANIFEST_REL).exists())

    def test_apply_refuses_when_the_draft_changed_after_validation(self) -> None:
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        other = self.repo / "gate2.sh"
        write(other, "#!/bin/sh\nexit 0\n")
        other.chmod(0o755)
        self.wire("draft", "--check", "other::./gate2.sh")
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / MANIFEST_REL).exists())

    def test_apply_refuses_to_clobber_an_existing_manifest_without_force(self) -> None:
        write(self.repo / MANIFEST_REL, '{"schema_version": 1, "command": ["./x"]}\n')
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        result = self.wire("apply", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.wire("apply", "--force")
        manifest = json.loads((self.repo / MANIFEST_REL).read_text())
        self.assertEqual(manifest["command"], ["./scripts/land-work-verifier.py"])

    def test_installed_wrapper_satisfies_the_land_work_verifier_contract(self) -> None:
        """End-to-end: land-work's own runner must accept what we install."""
        self.wire("draft", "--check", self.passing_check())
        self.wire("validate")
        self.wire("apply")
        runner = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-run-verifier.py"
        write(self.repo / "change.txt", "changed\n")
        git(self.repo, "add", "change.txt")
        git(self.repo, "commit", "-m", "change")
        base_sha = git(self.repo, "rev-parse", "HEAD~1").stdout.strip()
        head_sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        result = run(
            [
                str(runner),
                "--repo-root",
                str(self.repo),
                "--candidate",
                str(self.repo),
                "--base-sha",
                base_sha,
                "--head-sha",
                head_sha,
            ],
            self.repo,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        diagnostics = json.loads(result.stdout)
        self.assertEqual(diagnostics["verifier_status"], "passed")
        self.assertGreaterEqual(diagnostics["selected_check_count"], 1)


if __name__ == "__main__":
    unittest.main()
