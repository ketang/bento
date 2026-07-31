import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.script_test_utils import git, run, write


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-discover.py"
BUNDLED_TEAMMATE_CONFIG = REPO_ROOT / "catalog/skills/swarm/references/config.json"
TEAMMATE_CONFIG_REL = Path(".agent-plugins/bento/bento/swarm/config.json")


class SwarmDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.xdg_config_home = Path(self.temp_dir.name) / "xdg"
        self.environment = patch.dict(
            os.environ, {"XDG_CONFIG_HOME": str(self.xdg_config_home)}
        )
        self.environment.start()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Swarm Discover Test")
        git(self.repo, "config", "user.email", "swarm-discover@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.environment.stop()
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

    def test_codex_defaults_to_bundled_inherited_teammate_settings(self) -> None:
        payload = self.run_discover("--runtime", "codex")

        self.assertIsNone(payload["teammate_model"])
        self.assertIsNone(payload["teammate_reasoning_effort"])
        self.assertEqual(
            payload["teammate_config_path"], str(BUNDLED_TEAMMATE_CONFIG.resolve())
        )

    def test_codex_repo_teammate_config_overrides_home(self) -> None:
        home_config = self.xdg_config_home / "agent-plugins/bento/bento/swarm/config.json"
        repo_config = self.repo / TEAMMATE_CONFIG_REL
        write(
            home_config,
            json.dumps(
                {
                    "codex": {
                        "model": "home-model",
                        "reasoning_effort": "medium",
                    }
                }
            ),
        )
        write(
            repo_config,
            json.dumps(
                {
                    "codex": {
                        "model": "repo-model",
                        "reasoning_effort": "high",
                    }
                }
            ),
        )

        payload = self.run_discover("--runtime", "codex")

        self.assertEqual(payload["teammate_model"], "repo-model")
        self.assertEqual(payload["teammate_reasoning_effort"], "high")
        self.assertEqual(payload["teammate_config_path"], str(repo_config.resolve()))

    def test_codex_home_teammate_config_overrides_bundled_default(self) -> None:
        home_config = self.xdg_config_home / "agent-plugins/bento/bento/swarm/config.json"
        write(
            home_config,
            json.dumps(
                {
                    "codex": {
                        "model": "home-model",
                        "reasoning_effort": "low",
                    }
                }
            ),
        )

        payload = self.run_discover("--runtime", "codex")

        self.assertEqual(payload["teammate_model"], "home-model")
        self.assertEqual(payload["teammate_reasoning_effort"], "low")
        self.assertEqual(payload["teammate_config_path"], str(home_config.resolve()))

    def test_non_codex_runtimes_do_not_consume_teammate_config(self) -> None:
        write(
            self.repo / TEAMMATE_CONFIG_REL,
            json.dumps(
                {
                    "codex": {
                        "model": "codex-only-model",
                        "reasoning_effort": "high",
                    }
                }
            ),
        )

        for runtime in ("claude", "auto"):
            with self.subTest(runtime=runtime):
                payload = self.run_discover("--runtime", runtime)
                self.assertIsNone(payload["teammate_model"])
                self.assertIsNone(payload["teammate_reasoning_effort"])
                self.assertIsNone(payload["teammate_config_path"])

    def test_codex_teammate_config_rejects_invalid_values(self) -> None:
        repo_config = self.repo / TEAMMATE_CONFIG_REL
        invalid_cases = (
            ("malformed JSON", "{", "invalid JSON"),
            ("non-object codex", json.dumps({"codex": []}), "codex"),
            (
                "non-string model",
                json.dumps({"codex": {"model": 5}}),
                "codex.model",
            ),
            (
                "empty model",
                json.dumps({"codex": {"model": " "}}),
                "codex.model",
            ),
            (
                "non-string reasoning effort",
                json.dumps({"codex": {"reasoning_effort": False}}),
                "codex.reasoning_effort",
            ),
            (
                "empty reasoning effort",
                json.dumps({"codex": {"reasoning_effort": ""}}),
                "codex.reasoning_effort",
            ),
        )

        for label, content, expected_error in invalid_cases:
            with self.subTest(label=label):
                write(repo_config, content)
                result = run(
                    [str(SCRIPT), "--runtime", "codex"],
                    self.repo,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(repo_config.resolve()), result.stderr)
                self.assertIn(expected_error, result.stderr)

    def test_codex_teammate_config_ignores_unknown_keys(self) -> None:
        repo_config = self.repo / TEAMMATE_CONFIG_REL
        write(
            repo_config,
            json.dumps(
                {
                    "future_top_level": True,
                    "codex": {"future_codex_setting": "preserved-for-later"},
                }
            ),
        )

        payload = self.run_discover("--runtime", "codex")

        self.assertIsNone(payload["teammate_model"])
        self.assertIsNone(payload["teammate_reasoning_effort"])
        self.assertEqual(payload["teammate_config_path"], str(repo_config.resolve()))


if __name__ == "__main__":
    unittest.main()
