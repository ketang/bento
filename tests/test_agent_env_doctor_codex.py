import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "bento"
    / "codex"
    / "scripts"
    / "agent-env-doctor.py"
)


def load_module():
    loader = importlib.machinery.SourceFileLoader("agent_env_doctor_codex", str(SCRIPT))
    spec = importlib.util.spec_from_loader("agent_env_doctor_codex", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CodexAgentEnvDoctorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        # The Codex doctor acts only inside a git repo, so make one.
        subprocess.run(
            ["git", "init", "-q"], cwd=self.repo, check=True,
            capture_output=True,
        )
        self.mod = load_module()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _evaluate(self, **overrides):
        payload = {"session_id": "sess1", "cwd": str(self.repo)}
        payload.update(overrides)
        return self.mod.evaluate(payload)

    def _context(self, decision) -> str:
        self.assertIsNotNone(decision)
        return decision["hookSpecificOutput"]["additionalContext"]

    # --- check 1: imports (runtime-agnostic) --------------------------------

    def test_dangling_import_detected(self) -> None:
        (self.repo / "AGENTS.md").write_text(
            "@.agents/rules/style.md\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn(".agents/rules/style.md", context)
        self.assertIn("dangling", context)

    def test_valid_import_is_silent(self) -> None:
        (self.repo / "rules.md").write_text("Real.\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("@rules.md\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_code_fence_import_ignored(self) -> None:
        (self.repo / "AGENTS.md").write_text(
            "```\n@types/node\n```\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    # --- check 4: .agent-mode.local (runtime-agnostic) ----------------------

    def test_unknown_agent_mode_key_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text("bypass=true\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("unknown key", context)

    def test_recognized_keys_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "require_worktree=false\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_suppression_flag_silences_doctor(self) -> None:
        (self.repo / "AGENTS.md").write_text("@nope.md\n", encoding="utf-8")
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor=false\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    # --- Claude-only checks are absent --------------------------------------

    def test_hook_binary_check_not_run(self) -> None:
        # A missing registered hook command is a Claude-only check; the Codex
        # peer must not scan .claude/settings.json.
        settings_dir = self.repo / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": str(self.repo / "gone.sh"),
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertIsNone(self._evaluate())

    # --- contract -----------------------------------------------------------

    def test_non_git_dir_is_silent(self) -> None:
        non_git = self.root / "plain"
        non_git.mkdir()
        (non_git / "AGENTS.md").write_text("@gone.md\n", encoding="utf-8")
        self.assertIsNone(self._evaluate(cwd=str(non_git)))

    def test_output_shape_is_sessionstart(self) -> None:
        (self.repo / "AGENTS.md").write_text("@gone.md\n", encoding="utf-8")
        decision = self._evaluate()
        self.assertEqual(
            decision["hookSpecificOutput"]["hookEventName"], "SessionStart"
        )
        self.assertNotIn("decision", decision["hookSpecificOutput"])

    def test_never_blocks_and_exits_zero(self) -> None:
        (self.repo / "AGENTS.md").write_text("@gone.md\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps({"session_id": "s", "cwd": str(self.repo)}),
            capture_output=True,
            text=True,
            env={"HOME": str(self.root), "PATH": os.environ.get("PATH", "")},
        )
        self.assertEqual(result.returncode, 0)
        out = result.stdout.strip()
        if out:
            self.assertIn("hookSpecificOutput", json.loads(out))

    def test_malformed_stdin_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input="not json",
            capture_output=True,
            text=True,
            env={"HOME": str(self.root), "PATH": os.environ.get("PATH", "")},
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
