import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "bento"
    / "claude"
    / "scripts"
    / "agent-env-doctor.py"
)


def load_module():
    loader = importlib.machinery.SourceFileLoader("agent_env_doctor", str(SCRIPT))
    spec = importlib.util.spec_from_loader("agent_env_doctor", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class AgentEnvDoctorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        # Plugin registry the doctor reads; default empty so no plugin is
        # considered installed unless a test writes one.
        self.plugins_file = self.root / "installed_plugins.json"
        self._write_installed({})
        self.mod = load_module()

    def tearDown(self) -> None:
        self.temp.cleanup()

    # --- helpers ------------------------------------------------------------

    def _write_installed(self, plugins: dict) -> None:
        self.plugins_file.write_text(
            json.dumps({"plugins": plugins}), encoding="utf-8"
        )

    def _hook_input(self, **overrides) -> dict:
        payload = {"session_id": "sess1", "cwd": str(self.repo)}
        payload.update(overrides)
        return payload

    def _evaluate(self, env=None, **overrides):
        return self.mod.evaluate(
            self._hook_input(**overrides),
            home=self.home,
            env=env if env is not None else {"HOME": str(self.home), "PATH": ""},
            plugins_file=self.plugins_file,
        )

    def _context(self, decision) -> str:
        self.assertIsNotNone(decision)
        return decision["hookSpecificOutput"]["additionalContext"]

    # --- check 1: imports ---------------------------------------------------

    def test_dangling_import_detected_and_named(self) -> None:
        (self.repo / "CLAUDE.md").write_text(
            "Read this.\n@.agents/rules/style.md\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn(".agents/rules/style.md", context)
        self.assertIn("dangling", context)

    def test_empty_import_detected(self) -> None:
        (self.repo / "rules.md").write_text("", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("@rules.md\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("empty @import", context)
        self.assertIn("rules.md", context)

    def test_file_where_dir_expected_detected(self) -> None:
        # .agents is a 0-byte file (removed submodule), so .agents/rules/x.md
        # can never resolve. This is the flotsam evidence case.
        (self.repo / ".agents").write_text("", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("@.agents/rules/x.md\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("directory is expected", context)

    def test_valid_import_is_silent(self) -> None:
        (self.repo / "rules.md").write_text("Real content.\n", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("@rules.md\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_recursive_import_following(self) -> None:
        (self.repo / "CLAUDE.md").write_text("@a.md\n", encoding="utf-8")
        (self.repo / "a.md").write_text("nested\n@missing.md\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("missing.md", context)

    def test_email_and_bare_token_not_treated_as_import(self) -> None:
        (self.repo / "CLAUDE.md").write_text(
            "Contact me@example.com about @dangerous mode.\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    # --- check 2: hook binaries ---------------------------------------------

    def _write_settings(self, payload: dict, name: str = "settings.json") -> None:
        settings_dir = self.repo / ".claude"
        settings_dir.mkdir(exist_ok=True)
        (settings_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_missing_hook_script_detected(self) -> None:
        self._write_settings(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(self.repo / "scripts" / "gone.sh"),
                                }
                            ],
                        }
                    ]
                }
            }
        )
        context = self._context(self._evaluate())
        self.assertIn("not found", context)
        self.assertIn("gone.sh", context)

    def test_hook_gating_on_missing_binary_detected(self) -> None:
        wrapper = self.repo / "guard.sh"
        wrapper.write_text(
            "#!/bin/sh\n"
            "if ! command -v tdd-guard >/dev/null 2>&1; then exit 0; fi\n"
            "tdd-guard \"$@\"\n",
            encoding="utf-8",
        )
        self._write_settings(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": str(wrapper)}]}
                    ]
                }
            }
        )
        # PATH empty => tdd-guard is not resolvable.
        context = self._context(self._evaluate(env={"HOME": str(self.home), "PATH": ""}))
        self.assertIn("tdd-guard", context)
        self.assertIn("inert hook", context)

    def test_unresolved_plugin_root_var_is_skipped(self) -> None:
        # ${CLAUDE_PLUGIN_ROOT} is undefined here; the command must be skipped,
        # not false-flagged as missing.
        self._write_settings(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "${CLAUDE_PLUGIN_ROOT}/hooks/x.py",
                                }
                            ]
                        }
                    ]
                }
            }
        )
        self.assertIsNone(self._evaluate())

    # --- check 3: dormant plugins -------------------------------------------

    def test_dormant_plugin_nudge(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        context = self._context(self._evaluate())
        self.assertIn("storystore", context)
        self.assertIn("dormant", context)
        self.assertIn("docs/stories", context)

    def test_plugin_with_precondition_met_is_silent(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        (self.repo / "docs" / "stories").mkdir(parents=True)
        self.assertIsNone(self._evaluate())

    def test_uninstalled_plugin_never_nudges(self) -> None:
        # storystore not installed => no nudge even though docs/stories absent.
        self.assertIsNone(self._evaluate())

    def test_bugshot_dormant_uses_capture_command_precondition(self) -> None:
        self._write_installed({"bugshot@bento": [{"version": "1.0.0"}]})
        context = self._context(self._evaluate())
        self.assertIn("bugshot", context)
        self.assertIn("capture-command", context)

    # --- check 4: .agent-mode.local -----------------------------------------

    def test_bare_token_in_agent_mode_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text("dangerous\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("dangerous", context)
        self.assertIn("not a key=value", context)

    def test_unknown_key_in_agent_mode_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text("bypass=true\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("unknown key", context)
        self.assertIn("bypass", context)

    def test_recognized_agent_mode_keys_are_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "# comment\nrequire_worktree=false\nhygiene_check=false\n",
            encoding="utf-8",
        )
        self.assertIsNone(self._evaluate())

    # --- orchestration / contract ------------------------------------------

    def test_clean_repo_is_silent(self) -> None:
        (self.repo / "CLAUDE.md").write_text("No imports here.\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_suppression_flag_silences_doctor(self) -> None:
        # A real problem exists (dangling import) but doctor is suppressed.
        (self.repo / "CLAUDE.md").write_text("@nope.md\n", encoding="utf-8")
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor=false\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_no_cwd_is_silent(self) -> None:
        self.assertIsNone(
            self.mod.evaluate(
                {"session_id": "sess1"},
                home=self.home,
                env={"HOME": str(self.home), "PATH": ""},
                plugins_file=self.plugins_file,
            )
        )

    def test_output_is_sessionstart_additional_context(self) -> None:
        (self.repo / "CLAUDE.md").write_text("@gone.md\n", encoding="utf-8")
        decision = self._evaluate()
        self.assertIsNotNone(decision)
        self.assertEqual(
            decision["hookSpecificOutput"]["hookEventName"], "SessionStart"
        )
        self.assertIn("additionalContext", decision["hookSpecificOutput"])

    def test_never_blocks_and_exits_zero(self) -> None:
        # End-to-end: even with problems present, the process exits 0 and emits
        # only a hookSpecificOutput object (never a blocking decision).
        (self.repo / "CLAUDE.md").write_text("@gone.md\n", encoding="utf-8")
        payload = json.dumps(self._hook_input())
        result = subprocess.run(
            ["python3", str(SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        # Output (if any) must be a SessionStart additionalContext object, never
        # {"decision": "block"} or exit code 2.
        out = result.stdout.strip()
        if out:
            parsed = json.loads(out)
            self.assertIn("hookSpecificOutput", parsed)
            self.assertNotIn("decision", parsed)

    def test_malformed_stdin_exits_zero(self) -> None:
        result = subprocess.run(
            ["python3", str(SCRIPT)],
            input="not json",
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
