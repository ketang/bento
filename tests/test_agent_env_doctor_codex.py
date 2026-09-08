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
        self.home = self.root / "home"
        self.home.mkdir()
        # Empty by default so the stale-preview and orphan-worktree checks
        # never pick up real host state unless a test deliberately populates
        # it.
        self.tmp_root = self.root / "tmp"
        self.tmp_root.mkdir()
        self.mod = load_module()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _evaluate(self, home=None, tmp_root=None, now=None, **overrides):
        payload = {"session_id": "sess1", "cwd": str(self.repo)}
        payload.update(overrides)
        return self.mod.evaluate(
            payload,
            home=home if home is not None else self.home,
            tmp_root=tmp_root if tmp_root is not None else self.tmp_root,
            now=now,
        )

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

    # --- check 5: bare primary checkout with a working tree -----------------

    def test_bare_primary_with_working_tree_detected(self) -> None:
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init", "-q"],
            cwd=self.repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "core.bare", "true"],
            cwd=self.repo, check=True, capture_output=True,
        )
        (self.repo / "some-file.txt").write_text("hi\n", encoding="utf-8")
        context = self._context(self._evaluate())
        self.assertIn("core.bare", context)

    # --- check 6: prunable git worktrees -------------------------------------

    def test_unrelated_git_failure_does_not_fall_back_to_cwd(self) -> None:
        # A .git dir that git itself refuses to recognize for a reason
        # *other* than the bare-checkout bug (here: no HEAD/refs at all, so
        # `git rev-parse --show-toplevel` fails with "not a git repository")
        # must stay silent, not be treated as a project root via the
        # bare-checkout fallback.
        import shutil as _shutil

        _shutil.rmtree(self.repo / ".git")
        (self.repo / ".git").mkdir()
        (self.repo / ".git" / "config").write_text(
            "[core]\n\tbare = false\n", encoding="utf-8"
        )
        (self.repo / "AGENTS.md").write_text("@gone.md\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_prunable_worktree_detected(self) -> None:
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init", "-q"],
            cwd=self.repo, check=True, capture_output=True,
        )
        linked = self.root / "linked"
        subprocess.run(
            ["git", "worktree", "add", str(linked), "-b", "feature", "-q"],
            cwd=self.repo, check=True, capture_output=True,
        )
        import shutil as _shutil

        _shutil.rmtree(linked)
        context = self._context(self._evaluate())
        self.assertIn("prunable", context)

    # --- check 7: stale previews and orphan worktree directories -----------

    def test_stale_preview_dir_flagged(self) -> None:
        preview = self.tmp_root / "land-work-preview-abc123"
        preview.mkdir()
        old_time = 1_000_000.0
        os.utime(preview, (old_time, old_time))
        context = self._context(self._evaluate(now=old_time + 25 * 3600))
        self.assertIn("stale land-work preview", context)

    def test_orphan_worktree_directory_flagged(self) -> None:
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init", "-q"],
            cwd=self.repo, check=True, capture_output=True,
        )
        wt_root = self.home / ".local" / "share" / "worktrees" / self.repo.name
        wt_root.mkdir(parents=True)
        (wt_root / "dead-branch").mkdir()
        context = self._context(self._evaluate())
        self.assertIn("orphan worktree directory", context)

    # --- check 8: orphan dolt sql-server --------------------------------------

    def test_orphan_dolt_server_detected(self) -> None:
        beads_dir = self.repo / ".beads"
        beads_dir.mkdir()
        dolt_dir = beads_dir / "dolt"
        fake = subprocess.Popen(
            ["sh", "-c", f"sleep 30 # dolt sql-server {dolt_dir}"]
        )
        try:
            import time as _time

            _time.sleep(0.3)
            context = self._context(self._evaluate())
            self.assertIn("orphan dolt sql-server", context)
        finally:
            fake.terminate()
            fake.wait(timeout=5)

    def test_dolt_server_with_port_file_present_is_silent(self) -> None:
        beads_dir = self.repo / ".beads"
        beads_dir.mkdir()
        (beads_dir / "dolt-server.port").write_text("12345\n", encoding="utf-8")
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
