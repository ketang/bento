import json
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, run, write


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-discover.py"


class SwarmDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Swarm Discover Test")
        git(self.repo, "config", "user.email", "swarm-discover@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_discover(self, *args: str, cwd: Path | None = None) -> dict:
        result = run([str(SCRIPT), *args], cwd or self.repo)
        return json.loads(result.stdout)

    def test_discover_reports_git_defaults_without_config(self) -> None:
        payload = self.run_discover()

        self.assertEqual(payload["runtime"], "auto")
        self.assertEqual(payload["repo_root"], str(self.repo.resolve()))
        self.assertEqual(payload["primary_checkout_root"], str(self.repo.resolve()))
        self.assertEqual(payload["integration_branch"], "main")
        self.assertFalse(payload["linked_worktree"])
        self.assertFalse(payload["config_found"])
        self.assertIsNone(payload["config_path"])
        self.assertIn("origin/HEAD unavailable; primary branch detected from local refs", payload["warnings"])

    def test_discover_prefers_claude_config_for_claude_runtime(self) -> None:
        write(
            self.repo / ".codex/swarm-config.json",
            json.dumps({"integration_branch": "develop", "tracker": "linear"}),
        )
        write(
            self.repo / ".claude/swarm-config.json",
            json.dumps({"integration_branch": "release", "tracker": "jira", "quality_gates": ["tests"]}),
        )
        write(self.repo / "swarm-config.json", json.dumps({"integration_branch": "root"}))

        payload = self.run_discover("--runtime", "claude")

        self.assertTrue(payload["config_found"])
        self.assertEqual(payload["runtime"], "claude")
        self.assertEqual(payload["integration_branch"], "release")
        self.assertEqual(payload["tracker"], "jira")
        self.assertEqual(payload["quality_gates"], ["tests"])
        self.assertEqual(payload["config_path"], str((self.repo / ".claude/swarm-config.json").resolve()))

    def test_discover_prefers_codex_config_for_codex_runtime(self) -> None:
        write(
            self.repo / ".codex/swarm-config.json",
            json.dumps({"integration_branch": "develop", "tracker": "linear", "quality_gates": ["unit"]}),
        )
        write(
            self.repo / ".claude/swarm-config.json",
            json.dumps({"integration_branch": "release", "tracker": "jira"}),
        )
        write(self.repo / "swarm-config.json", json.dumps({"integration_branch": "root"}))

        payload = self.run_discover("--runtime", "codex")

        self.assertTrue(payload["config_found"])
        self.assertEqual(payload["runtime"], "codex")
        self.assertEqual(payload["integration_branch"], "develop")
        self.assertEqual(payload["tracker"], "linear")
        self.assertEqual(payload["quality_gates"], ["unit"])
        self.assertEqual(payload["config_path"], str((self.repo / ".codex/swarm-config.json").resolve()))

    def test_discover_auto_requires_runtime_when_both_runtime_configs_exist(self) -> None:
        write(
            self.repo / ".codex/swarm-config.json",
            json.dumps({"integration_branch": "develop"}),
        )
        write(
            self.repo / ".claude/swarm-config.json",
            json.dumps({"integration_branch": "release"}),
        )

        payload = self.run_discover()

        self.assertFalse(payload["config_found"])
        self.assertIsNone(payload["config_path"])
        self.assertEqual(payload["integration_branch"], "main")
        self.assertIn(
            "multiple runtime-specific swarm configs found; rerun with --runtime claude or --runtime codex",
            payload["warnings"],
        )

    def test_landing_target_flag_overrides_integration_branch(self) -> None:
        payload = self.run_discover("--landing-target", "release-branch")
        self.assertEqual(payload["integration_branch"], "release-branch")
        self.assertEqual(payload["landing_target"], "release-branch")

    def test_landing_target_defaults_echo_integration_branch(self) -> None:
        payload = self.run_discover()
        self.assertEqual(payload["landing_target"], payload["integration_branch"])


if __name__ == "__main__":
    unittest.main()
