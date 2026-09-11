import datetime
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
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
        # Empty by default so the stale-preview and orphan-worktree checks
        # never pick up real host state (e.g. actual /tmp/land-work-preview-*
        # dirs) unless a test deliberately populates it.
        self.tmp_root = self.root / "tmp"
        self.tmp_root.mkdir()
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

    def _evaluate(self, env=None, tmp_root=None, now=None, today=None, **overrides):
        return self.mod.evaluate(
            self._hook_input(**overrides),
            home=self.home,
            env=env if env is not None else {"HOME": str(self.home), "PATH": ""},
            plugins_file=self.plugins_file,
            tmp_root=tmp_root if tmp_root is not None else self.tmp_root,
            now=now,
            today=today,
        )

    def _context(self, decision) -> str:
        self.assertIsNotNone(decision)
        return decision["hookSpecificOutput"]["additionalContext"]

    def _run_script(self, payload: str, env_overrides=None):
        """Run the hook as a subprocess in a hermetic environment: a fake HOME
        (so the developer's real plugin registry never leaks into the result)
        and an empty PATH. Launched via the interpreter's absolute path so the
        empty PATH does not break process spawning."""
        env = {
            "HOME": str(self.home),
            "PATH": "",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
        )

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

    # -- bento-rdtn.2: dormant-plugin decision path ---------------------------

    def test_first_sighting_shows_full_nudge_with_three_options(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        context = self._context(self._evaluate())
        self.assertIn("storystore", context)
        self.assertIn("dormant", context)
        self.assertIn("wire it now", context)
        self.assertIn("agent_env_doctor_skip_plugin=storystore", context)
        self.assertIn("agent_env_doctor_remind_after=storystore:<YYYY-MM-DD>", context)

    def test_first_sighting_records_seen_in_agent_mode_local(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        self._evaluate()
        text = (self.repo / ".agent-mode.local").read_text(encoding="utf-8")
        self.assertIn("agent_env_doctor_seen=storystore", text)

    def test_recording_a_decision_preserves_an_unrelated_crlf_dangerous_line(self) -> None:
        # Code review: rewriting .agent-mode.local to record a dormant-plugin
        # decision must not silently normalize an unrelated CRLF-terminated
        # "dangerous\r\n" line into a bare "dangerous" line -- the trailing
        # \r is what keeps the launcher's exact bash `case` match from
        # activating on it (see the CRLF tests in check_agent_mode above);
        # losing it here would be a silent, unrelated privilege escalation.
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_bytes(b"dangerous\r\n")
        self._evaluate()
        raw = (self.repo / ".agent-mode.local").read_bytes()
        self.assertIn(b"dangerous\r\n", raw)
        self.assertIn(b"agent_env_doctor_seen=storystore", raw)

    def test_second_sighting_collapses_to_one_line(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        self._evaluate()  # first sighting: records "seen"
        context = self._context(self._evaluate())
        self.assertIn("storystore dormant — decision pending, see .agent-mode.local", context)
        self.assertNotIn("wire it now", context)

    def test_seen_marker_set_directly_also_collapses(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_seen=storystore\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("storystore dormant — decision pending", context)
        self.assertNotIn("wire it now", context)

    def test_skip_plugin_still_fully_silences_even_if_seen(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_seen=storystore\n"
            "agent_env_doctor_skip_plugin=storystore\n",
            encoding="utf-8",
        )
        self.assertIsNone(self._evaluate())

    def test_remind_after_future_date_fully_suppresses(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_remind_after=storystore:2999-01-01\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate(today=datetime.date(2026, 1, 1)))

    def test_remind_after_past_date_shows_full_nudge_once(self) -> None:

        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_remind_after=storystore:2026-01-01\n", encoding="utf-8"
        )
        context = self._context(self._evaluate(today=datetime.date(2026, 6, 1)))
        self.assertIn("wire it now", context)

    def test_remind_after_expiry_clears_the_entry_and_marks_seen(self) -> None:

        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_remind_after=storystore:2026-01-01\n", encoding="utf-8"
        )
        self._evaluate(today=datetime.date(2026, 6, 1))
        text = (self.repo / ".agent-mode.local").read_text(encoding="utf-8")
        self.assertIn("agent_env_doctor_seen=storystore", text)
        self.assertNotIn("agent_env_doctor_remind_after", text)

        # Next session collapses to the short form.
        context = self._context(self._evaluate(today=datetime.date(2026, 6, 2)))
        self.assertIn("storystore dormant — decision pending", context)
        self.assertNotIn("wire it now", context)

    def test_remind_after_preserves_other_plugins_entries(self) -> None:

        self._write_installed(
            {"storystore@bento": [{"version": "1.0.0"}], "bugshot@bento": [{"version": "1.0.0"}]}
        )
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_remind_after=storystore:2026-01-01,bugshot:2999-01-01\n",
            encoding="utf-8",
        )
        self._evaluate(today=datetime.date(2026, 6, 1))
        text = (self.repo / ".agent-mode.local").read_text(encoding="utf-8")
        self.assertIn("agent_env_doctor_seen=storystore", text)
        self.assertIn("agent_env_doctor_remind_after=bugshot:2999-01-01", text)
        self.assertNotIn("storystore:2026-01-01", text)

    def test_remind_after_malformed_date_fails_safe_to_full_nudge(self) -> None:
        self._write_installed({"storystore@bento": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_remind_after=storystore:not-a-date\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("wire it now", context)

    def test_remind_after_unknown_plugin_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_remind_after=nope:2026-01-01\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("unknown plugin", context)
        self.assertIn("nope", context)

    def test_remind_after_malformed_entry_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_remind_after=storystore\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("not <plugin>:<date>", context)

    def test_remind_after_bad_date_format_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_remind_after=storystore:01/01/2026\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("not a YYYY-MM-DD date", context)

    def test_seen_key_with_unknown_plugin_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_seen=nope\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("unknown plugin", context)
        self.assertIn("nope", context)

    def test_bugshot_dormant_uses_capture_command_precondition(self) -> None:
        self._write_installed({"bugshot@bento": [{"version": "1.0.0"}]})
        context = self._context(self._evaluate())
        self.assertIn("bugshot", context)
        self.assertIn("capture-command", context)

    def test_skip_plugin_marker_silences_only_that_plugins_dormancy(self) -> None:
        self._write_installed(
            {
                "bugshot@bento": [{"version": "1.0.0"}],
                "storystore@bento": [{"version": "1.0.0"}],
            }
        )
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_skip_plugin=bugshot\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertNotIn("bugshot", context)
        self.assertIn("storystore", context)
        self.assertIn("dormant", context)

    def test_skip_plugin_marker_accepts_comma_separated_list(self) -> None:
        self._write_installed(
            {
                "bugshot@bento": [{"version": "1.0.0"}],
                "storystore@bento": [{"version": "1.0.0"}],
            }
        )
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_skip_plugin=bugshot, storystore\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_skip_plugin_marker_still_surfaces_other_checks(self) -> None:
        # The per-plugin marker must not act like the global kill switch: a
        # malformed .agent-mode.local line still gets flagged.
        self._write_installed({"bugshot@bento": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_skip_plugin=bugshot\nbroken-line\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertNotIn("bugshot is installed but dormant", context)
        self.assertIn("not a key=value", context)

    def test_skip_plugin_marker_is_recognized_key(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_skip_plugin=bugshot\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_skip_plugin_marker_unknown_plugin_name_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_skip_plugin=bugshoot\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("unknown plugin", context)
        self.assertIn("bugshoot", context)

    def test_skip_plugin_marker_boolean_value_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_skip_plugin=false\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("unknown plugin", context)
        self.assertIn("false", context)

    def test_skip_plugin_marker_partial_unknown_name_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_skip_plugin=bugshot, nope\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("unknown plugin", context)
        self.assertIn("nope", context)

    # --- check 4: .agent-mode.local -----------------------------------------

    def test_bare_dangerous_token_is_silent(self) -> None:
        # "dangerous" is real launcher grammar (bashrc.agent-mode.sh) that
        # enables --dangerously-skip-permissions; it is not a Bento no-op.
        (self.repo / ".agent-mode.local").write_text("dangerous\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_other_bare_token_still_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text("yolo\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("yolo", context)
        self.assertIn("not a key=value", context)

    def test_whitespace_padded_dangerous_token_still_flagged(self) -> None:
        # The launcher's bash `case "$line" in "dangerous")` matches the raw
        # line from `IFS= read -r line` with zero whitespace tolerance — a
        # trailing-space-padded "dangerous " does NOT activate dangerous mode
        # in the real launcher, so Bento must still warn on it rather than
        # silently accept it as valid launcher grammar.
        (self.repo / ".agent-mode.local").write_text("dangerous \n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("not a key=value", context)

    def test_leading_whitespace_padded_dangerous_token_still_flagged(self) -> None:
        (self.repo / ".agent-mode.local").write_text("  dangerous\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("not a key=value", context)

    def test_crlf_dangerous_token_still_flagged(self) -> None:
        # A CRLF-terminated "dangerous\r\n" line (e.g. saved by a Windows
        # editor) becomes "dangerous\r" to bash's `IFS= read -r line` — its
        # exact-match `case` does NOT activate on that, so this is broken
        # config that looks like it enables dangerous mode but doesn't. The
        # doctor must still warn rather than silently accept it.
        (self.repo / ".agent-mode.local").write_bytes(b"dangerous\r\n")
        context = self._context(self._evaluate())
        self.assertIn("not a key=value", context)

    def test_launcher_mode_assignment_is_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_mode_and_tools_assignment_is_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\ntools = ["claude", "codex"]\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_tools_missing_comma_is_silent(self) -> None:
        # The real launcher greps for quoted tokens anywhere on a `tools =`
        # line (_agent_mode_tools_line / _agent_mode_tool_enabled) — a
        # missing comma between entries is still real, effective config, not
        # malformed input.
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\ntools = ["claude" "codex"]\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_tools_trailing_comma_is_silent(self) -> None:
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\ntools = ["claude", "codex",]\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_launcher_mode_non_dangerous_value_is_silent(self) -> None:
        # The launcher itself decides whether a given mode value activates
        # anything; any quoted value is valid launcher syntax for Bento.
        (self.repo / ".agent-mode.local").write_text(
            'mode = "safe"\n', encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_unquoted_mode_assignment_still_flagged(self) -> None:
        # The launcher's own parser requires quotes; unquoted values are not
        # recognized launcher syntax, so this remains a genuine Bento warning.
        (self.repo / ".agent-mode.local").write_text(
            "mode=dangerous\n", encoding="utf-8"
        )
        context = self._context(self._evaluate())
        self.assertIn("unknown key", context)
        self.assertIn("mode", context)

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

    def test_launcher_and_bento_settings_coexist(self) -> None:
        # Launcher-owned mode/tools lines and Bento's own key=value settings
        # can appear in the same file without tripping each other's checks.
        (self.repo / ".agent-mode.local").write_text(
            'mode = "dangerous"\n'
            'tools = ["claude"]\n'
            "require_worktree=false\n"
            "hygiene_check=false\n",
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
        result = self._run_script(json.dumps(self._hook_input()))
        self.assertEqual(result.returncode, 0)
        # Output (if any) must be a SessionStart additionalContext object, never
        # {"decision": "block"} or exit code 2.
        out = result.stdout.strip()
        if out:
            parsed = json.loads(out)
            self.assertIn("hookSpecificOutput", parsed)
            self.assertNotIn("decision", parsed)

    def test_malformed_stdin_exits_zero(self) -> None:
        result = self._run_script("not json")
        self.assertEqual(result.returncode, 0)

    # --- regression: false-positive generators ------------------------------

    def test_import_token_in_code_fence_ignored(self) -> None:
        # B1: @tokens inside a fenced code block are code, not doc imports.
        (self.repo / "CLAUDE.md").write_text(
            "See the config:\n```json\n\"deps\": [\"@types/node\"]\n```\n"
            "and inline `@app.route(\"/health\")` too.\n",
            encoding="utf-8",
        )
        self.assertIsNone(self._evaluate())

    def test_package_spec_token_not_flagged(self) -> None:
        # B1: @types/node in prose has no doc extension and no existing-dir
        # prefix, so it is not a dangling import.
        (self.repo / "CLAUDE.md").write_text(
            "Install @types/node and @scope/pkg for typings.\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_decorator_prose_not_flagged(self) -> None:
        # B1: @app.route("/health") in prose must not be flagged.
        (self.repo / "AGENTS.md").write_text(
            "The handler is registered with @app.route(\"/health\").\n",
            encoding="utf-8",
        )
        self.assertIsNone(self._evaluate())

    def test_existing_dir_prefix_dangling_import_still_flagged(self) -> None:
        # B1: an extension-less token into a real directory is still an import.
        (self.repo / "docs").mkdir()
        (self.repo / "CLAUDE.md").write_text("@docs/missing-guide\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("docs/missing-guide", context)
        self.assertIn("dangling", context)

    def test_trailing_backtick_token_resolves(self) -> None:
        # B5: '@docs/setup.md`,' must strip both the comma and the backtick and
        # resolve to the real, non-empty file (so: silent).
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "setup.md").write_text("real\n", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text(
            "Read @docs/setup.md`, please.\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_import_cycle_terminates_without_spam(self) -> None:
        # a.md <-> b.md mutually import each other; must terminate, no warnings.
        (self.repo / "CLAUDE.md").write_text("@a.md\n", encoding="utf-8")
        (self.repo / "a.md").write_text("A\n@b.md\n", encoding="utf-8")
        (self.repo / "b.md").write_text("B\n@a.md\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_gate_regex_does_not_match_find_type_flag(self) -> None:
        # B4: `find . -type f` inside a wrapper must not register 'f' (or any
        # token) as a gated binary => no inert-hook warning.
        wrapper = self.repo / "guard.sh"
        wrapper.write_text(
            "#!/bin/sh\nfind . -type f -name '*.py'\n# decide which formatter\n",
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
        self.assertIsNone(self._evaluate())

    def test_quoted_hook_command_with_args_not_false_flagged(self) -> None:
        # B2: a quoted command path with a trailing flag must resolve to the
        # real script, not to a quote-wrapped path that "does not exist".
        wrapper = self.repo / "hook.sh"
        wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self._write_settings(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'"{wrapper}" --fast',
                                }
                            ]
                        }
                    ]
                }
            }
        )
        self.assertIsNone(self._evaluate())

    def test_env_assignment_prefix_not_false_flagged(self) -> None:
        # B3: `FOO=1 <script>` must skip the assignment and judge the script,
        # not shutil.which("FOO=1").
        wrapper = self.repo / "hook.sh"
        wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self._write_settings(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f"FOO=1 BAR=2 {wrapper}",
                                }
                            ]
                        }
                    ]
                }
            }
        )
        self.assertIsNone(self._evaluate())

    def test_shell_builtin_hook_command_not_false_flagged(self) -> None:
        # B3: a builtin/keyword as the effective command cannot be judged.
        self._write_settings(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {"type": "command", "command": "[ -x /bin/true ]"}
                            ]
                        }
                    ]
                }
            }
        )
        self.assertIsNone(self._evaluate())

    def test_plugin_root_command_skipped_even_when_var_set(self) -> None:
        # B6: a command referencing ${CLAUDE_PLUGIN_ROOT} must be skipped even
        # when that variable is defined in the doctor's own environment (it
        # points at bento's root, not the other plugin's).
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
        env = {
            "HOME": str(self.home),
            "PATH": "",
            "CLAUDE_PLUGIN_ROOT": str(self.root / "bento-plugin-root"),
        }
        self.assertIsNone(self._evaluate(env=env))

    def test_settings_local_json_is_scanned(self) -> None:
        # settings.local.json is scanned alongside settings.json.
        self._write_settings(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(self.repo / "nope.sh"),
                                }
                            ]
                        }
                    ]
                }
            },
            name="settings.local.json",
        )
        context = self._context(self._evaluate())
        self.assertIn("nope.sh", context)
        self.assertIn("settings.local.json", context)

    def test_malformed_settings_json_flagged(self) -> None:
        settings_dir = self.repo / ".claude"
        settings_dir.mkdir(exist_ok=True)
        (settings_dir / "settings.json").write_text("{not json", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("unreadable hook config", context)
        self.assertIn("settings.json", context)

    def test_unreadable_agent_doc_exits_zero(self) -> None:
        # A doc the process cannot read must not crash the hook (fix A: every
        # path, including read errors, ends in exit 0).
        doc = self.repo / "CLAUDE.md"
        doc.write_text("@gone.md\n", encoding="utf-8")
        os.chmod(doc, 0o000)
        try:
            result = self._run_script(json.dumps(self._hook_input()))
        finally:
            os.chmod(doc, 0o644)
        self.assertEqual(result.returncode, 0)

    # --- check 5: bare primary checkout with a working tree -----------------

    def test_bare_primary_with_working_tree_detected(self) -> None:
        git_dir = self.repo / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            "[core]\n\tbare = true\n", encoding="utf-8"
        )
        (self.repo / "some-file.txt").write_text("hi\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("core.bare", context)
        self.assertIn(".git/config", context)

    def test_bare_config_without_working_tree_files_is_silent(self) -> None:
        # A real bare repo has no working-tree files alongside .git — no bug.
        git_dir = self.repo / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            "[core]\n\tbare = true\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_non_bare_git_config_is_silent(self) -> None:
        git_dir = self.repo / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            "[core]\n\tbare = false\n", encoding="utf-8"
        )
        (self.repo / "some-file.txt").write_text("hi\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_bare_true_outside_core_section_not_flagged(self) -> None:
        # A same-named `bare = true` key in an unrelated section (e.g. a
        # submodule's) must not be mistaken for core.bare.
        git_dir = self.repo / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[core]\n\tbare = false\n[submodule "x"]\n\tbare = true\n',
            encoding="utf-8",
        )
        (self.repo / "some-file.txt").write_text("hi\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_linked_worktree_gitdir_file_not_flagged_as_bare(self) -> None:
        # A linked worktree's .git is a file (gitdir pointer), not a
        # directory; the bare-primary check must not misfire on it.
        (self.repo / ".git").write_text(
            "gitdir: /somewhere/.git/worktrees/x\n", encoding="utf-8"
        )
        (self.repo / "some-file.txt").write_text("hi\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    # --- check 6: prunable git worktrees -------------------------------------

    def _git(self, *args, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo, capture_output=True, text=True,
            check=True,
        )

    def test_prunable_worktree_detected(self) -> None:
        self._git("init", "-q")
        self._git("commit", "--allow-empty", "-m", "init", "-q")
        linked = self.root / "linked"
        self._git("worktree", "add", str(linked), "-b", "feature", "-q")
        import shutil as _shutil

        _shutil.rmtree(linked)
        context = self._context(self._evaluate())
        self.assertIn("prunable", context)

    def test_no_prunable_worktrees_is_silent(self) -> None:
        self._git("init", "-q")
        self._git("commit", "--allow-empty", "-m", "init", "-q")
        self.assertIsNone(self._evaluate())

    def test_non_git_repo_prune_check_is_silent(self) -> None:
        # self.repo has no .git at all in most tests; the prune check must
        # not misfire on git's "not a git repository" error output.
        self.assertIsNone(self._evaluate())

    # --- check 7: stale previews and orphan worktree directories -----------

    def test_stale_preview_dir_flagged(self) -> None:
        preview = self.tmp_root / "land-work-preview-abc123"
        preview.mkdir()
        old_time = 1_000_000.0
        os.utime(preview, (old_time, old_time))
        context = self._context(
            self._evaluate(now=old_time + 25 * 3600)
        )
        self.assertIn("stale land-work preview", context)
        self.assertIn(str(preview), context)

    def test_fresh_preview_dir_is_silent(self) -> None:
        preview = self.tmp_root / "land-work-preview-abc123"
        preview.mkdir()
        now = time.time()
        os.utime(preview, (now, now))
        self.assertIsNone(self._evaluate(now=now + 3600))

    def test_preview_max_age_override_respected(self) -> None:
        preview = self.tmp_root / "land-work-preview-abc123"
        preview.mkdir()
        old_time = 1_000_000.0
        os.utime(preview, (old_time, old_time))
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_preview_max_age_hours=48\n", encoding="utf-8"
        )
        # 25h old: stale under the 24h default but not under a 48h override.
        self.assertIsNone(self._evaluate(now=old_time + 25 * 3600))

    def test_orphan_worktree_directory_flagged(self) -> None:
        self._git("init", "-q")
        self._git("commit", "--allow-empty", "-m", "init", "-q")
        wt_root = self.home / ".local" / "share" / "worktrees" / self.repo.name
        wt_root.mkdir(parents=True)
        orphan = wt_root / "dead-branch"
        orphan.mkdir()
        context = self._context(self._evaluate())
        self.assertIn("orphan worktree directory", context)
        self.assertIn(str(orphan), context)

    def test_registered_worktree_directory_not_flagged(self) -> None:
        self._git("init", "-q")
        self._git("commit", "--allow-empty", "-m", "init", "-q")
        wt_root = self.home / ".local" / "share" / "worktrees" / self.repo.name
        wt_root.mkdir(parents=True)
        linked = wt_root / "feature"
        self._git("worktree", "add", str(linked), "-b", "feature", "-q")
        self.assertIsNone(self._evaluate())

    # --- check 8: orphan dolt sql-server --------------------------------------

    def test_orphan_dolt_server_detected(self) -> None:
        beads_dir = self.repo / ".beads"
        beads_dir.mkdir()
        dolt_dir = beads_dir / "dolt"
        # A process whose command-line args reference the dolt sql-server
        # binary and this repo's .beads/dolt path (the shell comment makes
        # `ps -eo pid,args` show these tokens without needing a real dolt
        # binary on PATH).
        fake = subprocess.Popen(
            ["sh", "-c", f"sleep 30 # dolt sql-server {dolt_dir}"]
        )
        try:
            time.sleep(0.3)
            decision = self._evaluate()
            context = self._context(decision)
            self.assertIn("orphan dolt sql-server", context)
            self.assertIn(str(fake.pid), context)
        finally:
            fake.terminate()
            fake.wait(timeout=5)

    def test_dolt_server_for_sibling_directory_not_flagged(self) -> None:
        # A dolt sql-server for a sibling directory whose path merely has
        # this repo's .beads/dolt as a *string prefix* (e.g. a "-staging"
        # suffix) must not be mistaken for this repo's orphan.
        beads_dir = self.repo / ".beads"
        beads_dir.mkdir()
        sibling_dolt_dir = str(beads_dir / "dolt") + "-staging"
        fake = subprocess.Popen(
            ["sh", "-c", f"sleep 30 # dolt sql-server {sibling_dolt_dir}"]
        )
        try:
            time.sleep(0.3)
            self.assertIsNone(self._evaluate())
        finally:
            fake.terminate()
            fake.wait(timeout=5)

    def test_dolt_server_cwd_in_sibling_directory_not_flagged(self) -> None:
        # A process whose cwd is a sibling directory that merely starts with
        # ".beads" as a string (e.g. ".beads-backup") must not be mistaken
        # for a process running inside this repo's .beads dir.
        beads_dir = self.repo / ".beads"
        beads_dir.mkdir()
        sibling = self.repo / ".beads-backup"
        sibling.mkdir()
        fake = subprocess.Popen(
            ["sh", "-c", "sleep 30 # dolt sql-server unrelated-path"],
            cwd=sibling,
        )
        try:
            time.sleep(0.3)
            self.assertIsNone(self._evaluate())
        finally:
            fake.terminate()
            fake.wait(timeout=5)

    def test_dolt_server_with_port_file_present_is_silent(self) -> None:
        beads_dir = self.repo / ".beads"
        beads_dir.mkdir()
        (beads_dir / "dolt-server.port").write_text("12345\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_no_beads_dir_skips_process_scan(self) -> None:
        self.assertIsNone(self._evaluate())

    def test_no_beads_dir_process_scan_never_invoked(self) -> None:
        # Patch subprocess.run to fail if the doctor ever shells out to `ps`
        # when .beads/ is absent — the acceptance contract for check 8.
        import unittest.mock as mock

        real_run = subprocess.run

        def guarded_run(args, *a, **kw):
            if args and args[0] == "ps":
                self.fail("ps was invoked despite no .beads/ directory")
            return real_run(args, *a, **kw)

        with mock.patch.object(subprocess, "run", side_effect=guarded_run):
            self.assertIsNone(self._evaluate())

    # --- latency ---------------------------------------------------------

    def test_healthy_repo_latency_under_budget(self) -> None:
        # A healthy repo (including a real .beads/ dir so the dolt-server
        # process scan runs) must add well under 300ms of SessionStart
        # latency.
        self._git("init", "-q")
        self._git("commit", "--allow-empty", "-m", "init", "-q")
        (self.repo / ".beads").mkdir()
        (self.repo / ".beads" / "dolt-server.port").write_text(
            "12345\n", encoding="utf-8"
        )
        start = time.monotonic()
        self.assertIsNone(self._evaluate())
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.3, f"doctor took {elapsed:.3f}s on a healthy repo")

    def test_closed_stdout_broken_pipe_exits_zero(self) -> None:
        # fix A: a BrokenPipeError while emitting the decision must not surface
        # as a nonzero exit. Give the child a dangling import so it produces
        # output, then close the read end of its stdout pipe before it writes.
        (self.repo / "CLAUDE.md").write_text("@gone.md\n", encoding="utf-8")
        payload = json.dumps(self._hook_input())
        read_fd, write_fd = os.pipe()
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=write_fd,
            stderr=subprocess.DEVNULL,
            env={"HOME": str(self.home), "PATH": ""},
        )
        os.close(write_fd)
        os.close(read_fd)  # no reader: any child write to stdout hits EPIPE
        proc.stdin.write(payload.encode())
        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=30), 0)

    # -- bento-rdtn.10: superpowers coexistence pointer ----------------------

    def test_superpowers_installed_shows_coexistence_pointer(self) -> None:
        self._write_installed({"superpowers@anthropic": [{"version": "1.0.0"}]})
        context = self._context(self._evaluate())
        self.assertIn("superpowers is also installed", context)
        self.assertIn("launch-work replaces", context)
        self.assertIn("land-work replaces", context)
        self.assertIn("docs/installing-plugins.md", context)

    def test_superpowers_not_installed_stays_silent(self) -> None:
        self.assertIsNone(self._evaluate())

    def test_superpowers_pointer_records_seen(self) -> None:
        self._write_installed({"superpowers@anthropic": [{"version": "1.0.0"}]})
        self._evaluate()
        text = (self.repo / ".agent-mode.local").read_text(encoding="utf-8")
        self.assertIn("agent_env_doctor_superpowers_pointer_seen=true", text)

    def test_superpowers_pointer_shown_only_once(self) -> None:
        self._write_installed({"superpowers@anthropic": [{"version": "1.0.0"}]})
        self._evaluate()  # first sighting: records seen
        self.assertIsNone(self._evaluate())

    def test_superpowers_pointer_seen_marker_set_directly_also_silences(self) -> None:
        self._write_installed({"superpowers@anthropic": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_text(
            "agent_env_doctor_superpowers_pointer_seen=true\n", encoding="utf-8"
        )
        self.assertIsNone(self._evaluate())

    def test_superpowers_pointer_recording_preserves_crlf_dangerous_line(self) -> None:
        self._write_installed({"superpowers@anthropic": [{"version": "1.0.0"}]})
        (self.repo / ".agent-mode.local").write_bytes(b"dangerous\r\n")
        self._evaluate()
        raw = (self.repo / ".agent-mode.local").read_bytes()
        self.assertIn(b"dangerous\r\n", raw)
        self.assertIn(b"agent_env_doctor_superpowers_pointer_seen=true", raw)

    def test_superpowers_pointer_coexists_with_dormant_plugin_nudge(self) -> None:
        # The two "seen" mechanisms live in the same file and must not
        # clobber each other on a single rewrite.
        self._write_installed(
            {
                "superpowers@anthropic": [{"version": "1.0.0"}],
                "storystore@bento": [{"version": "1.0.0"}],
            }
        )
        context = self._context(self._evaluate())
        self.assertIn("superpowers is also installed", context)
        self.assertIn("storystore", context)
        text = (self.repo / ".agent-mode.local").read_text(encoding="utf-8")
        self.assertIn("agent_env_doctor_superpowers_pointer_seen=true", text)
        self.assertIn("agent_env_doctor_seen=storystore", text)

        second_context = self._context(self._evaluate())
        self.assertNotIn("superpowers is also installed", second_context)
        self.assertIn("storystore dormant — decision pending", second_context)

    def test_no_agent_mode_local_file_gets_no_spurious_leading_blank_line(self) -> None:
        # Code review: writing the first-ever key into an absent
        # .agent-mode.local must not leave an empty first line ahead of it.
        self._write_installed({"superpowers@anthropic": [{"version": "1.0.0"}]})
        self._evaluate()
        text = (self.repo / ".agent-mode.local").read_text(encoding="utf-8")
        self.assertEqual(text, "agent_env_doctor_superpowers_pointer_seen=true\n")


if __name__ == "__main__":
    unittest.main()
