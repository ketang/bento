"""End-to-end test for the bash-telemetry PostToolUse hook.

Drives the real ``claude`` CLI against a mock Anthropic API served by
``zolem`` so we exercise the full hook-dispatch path for PostToolUse(Bash)
telemetry recording. The fixture instructs Claude to run a script whose
path matches the bento dev-layout pattern, triggering the telemetry hook
to write a JSONL record.
"""

from __future__ import annotations

import json
import shutil
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from tests.e2e_utils import E2ETestCase, _have

REPO_ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(
    _have("zolem") and _have("claude"),
    "zolem and claude must both be on PATH",
)
class BashTelemetryHookE2ETest(E2ETestCase):
    """Verify that the record-bash PostToolUse hook writes telemetry JSONL."""

    BACKEND = "fixture"
    FIXTURE_NS = "e2e-telemetry"

    def setUp(self) -> None:
        super().setUp()
        self.xdg_state = Path(self.tmp.name) / "state"
        self.xdg_state.mkdir(parents=True, exist_ok=True)

    def _init_repo_with_hook(self) -> Path:
        """Create a git repo wired with the bash-telemetry PostToolUse hook.

        The repo is structured as a bento source repository (with
        .claude-plugin markers) so the auto-allow PreToolUse hook recognises
        scripts inside it.  Both hooks are wired:

          PreToolUse  → auto-allow.py  (grants permission in --print mode)
          PostToolUse → record-bash.py (writes the telemetry JSONL record)
        """
        repo = self._init_repo()

        auto_allow_script = (
            REPO_ROOT
            / "catalog"
            / "hooks"
            / "bento"
            / "claude"
            / "scripts"
            / "auto-allow.py"
        )
        hook_script = (
            REPO_ROOT
            / "catalog"
            / "hooks"
            / "telemetry"
            / "claude"
            / "scripts"
            / "record-bash.py"
        )

        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                # auto-allow recognises scripts inside a bento
                                # source repo (detected via .claude-plugin).
                                "command": f"python3 {auto_allow_script} bento {repo}",
                            }
                        ],
                    }
                ],
                "PostToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"python3 {hook_script}",
                            }
                        ],
                    }
                ],
            }
        }
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )

        # Bento source-repo markers so auto-allow recognises scripts in repo.
        (repo / ".claude-plugin").mkdir()
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "bento"}) + "\n", encoding="utf-8"
        )
        plugin_meta = repo / "plugins" / "claude" / "bento" / ".claude-plugin"
        plugin_meta.mkdir(parents=True)
        (plugin_meta / "plugin.json").write_text(
            json.dumps({"name": "bento"}) + "\n", encoding="utf-8"
        )

        # Create a dummy bento-attributed script for the fixture command to
        # invoke.  The path matches DEV_LAYOUT_RE so the hook records it.
        script_dir = repo / "catalog" / "skills" / "test-e2e" / "scripts"
        script_dir.mkdir(parents=True)
        (script_dir / "noop.py").write_text(
            "# noop script for e2e telemetry test\n", encoding="utf-8"
        )

        return repo

    def test_hook_records_bash_event(self) -> None:
        repo = self._init_repo_with_hook()
        self._run_claude(
            repo,
            "say ok",
            extra_env={"XDG_STATE_HOME": str(self.xdg_state)},
        )

        # The hook writes to XDG_STATE_HOME/bento/telemetry/<date>.jsonl
        # The hook uses UTC for the file date; use UTC here to match.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl = self.xdg_state / "bento" / "telemetry" / f"{today}.jsonl"
        self.assertTrue(jsonl.exists(), f"telemetry JSONL not found: {jsonl}")

        lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreater(len(lines), 0, "JSONL file is empty")

        last = json.loads(lines[-1])

        # Fields from bento_telemetry.make_script_record
        self.assertEqual(last["kind"], "script")
        self.assertEqual(last["skill"], "test-e2e")
        self.assertEqual(last["script"], "noop.py")
        self.assertEqual(last["class"], "ok")
        self.assertEqual(last["exit"], 0)
        self.assertEqual(last["v"], 1)
        self.assertZolemHit()


if __name__ == "__main__":
    unittest.main()
