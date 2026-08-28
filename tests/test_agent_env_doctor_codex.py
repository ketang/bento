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

    def test_bare_dangerous_token_is_silent(self) -> None:
        # "dangerous" is real launcher grammar (bashrc.agent-mode.sh) that
        # enables --dangerously-bypass-approvals-and-sandbox for Codex.
        (self.repo / ".agent-mode.local").write_text("dangerous\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_other_bare_token_still_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text("yolo\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("not a key=value", context)

    def test_whitespace_padded_dangerous_token_still_flagged(self) -> None:
        # The launcher's bash `case "$line" in "dangerous")` matches the raw
        # line from `IFS= read -r line` with zero whitespace tolerance.
        (self.repo / ".agent-mode.local").write_text("dangerous \n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("not a key=value", context)

    def test_leading_whitespace_padded_dangerous_token_still_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text("  dangerous\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("not a key=value", context)

    def test_crlf_dangerous_token_still_flagged(self) -> None:
        # A CRLF-terminated "dangerous\r\n" line becomes "dangerous\r" to
        # bash's `IFS= read -r line` — its exact-match `case` does not
        # activate on that, so this broken config must still warn.
        (self.repo / ".agent-mode.local").write_bytes(b"dangerous\r\n")
        context = self._context(self._evaluate())
        self.assertIn("not a key=value", context)

    def test_launcher_mode_and_tools_assignment_is_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\ntools = ["claude", "codex"]\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_tools_missing_comma_is_silent(self) -> None:
        # The real launcher greps for quoted tokens anywhere on a `tools =`
        # line — a missing comma between entries is still real, effective
        # config, not malformed input.
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\ntools = ["claude" "codex"]\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_tools_trailing_comma_is_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\ntools = ["claude", "codex",]\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_mode_only_bare_line_is_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_mode_non_dangerous_value_is_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "safe"\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_unquoted_mode_assignment_still_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "mode=dangerous\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("unknown key", context)
        self.assertIn("mode", context)

    def test_launcher_and_bento_settings_coexist(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\ntools = ["codex"]\nrequire_worktree=false\n',
            encoding="utf-8",
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_settings_do_not_mask_real_bento_problem(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\nbypass=true\n', encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("unknown key", context)
        self.assertIn("bypass", context)

    def test_recognized_keys_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "require_worktree=false\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_skip_plugin_key_recognized(self) -> None:
        # agent_env_doctor_skip_plugin has no effect here (Codex runs no
        # dormant-plugin check), but it must not read as an unknown key.
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_skip_plugin=bugshot\n", encoding="utf-8"
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
