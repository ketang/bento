"""End-to-end test for the bento telemetry PostToolUse hook via codex.

Drives the real ``codex`` CLI against a mock OpenAI Responses API served by
``zolem`` to verify that the bento telemetry ``record-bash.py`` PostToolUse
hook fires and writes a JSONL record after codex executes a shell command
whose path matches the bento DEV_LAYOUT_RE pattern.

The test is skipped when ``zolem`` or ``codex`` is not on PATH.

Architecture:
  1. Start zolem on an OS-assigned port with a two-turn OpenAI v1-responses
     fixture: turn-tool (a local_shell_call for a bento script) → turn-end
     (text end_turn).
  2. Create a temp git repo structured as a bento source repo so that
     bento_telemetry.attribute() can match the script path to a skill.
  3. Run ``codex exec`` with:
       - CODEX_API_KEY=sk-test      forces API-key auth mode
       - openai_base_url=zolem      zolem proxies the Responses API WS
       - --dangerously-bypass-approvals-and-sandbox  skip approval prompts
       - --dangerously-bypass-hook-trust             load hooks without trust check
     The installed bento plugin's PostToolUse/Bash hook (record-bash.py) fires
     after the shell command executes.
  4. Assert that the telemetry JSONL was written with the expected fields.
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from e2e_utils import E2ETestCase, _have  # noqa: E402


RECORD_BASH_SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "telemetry"
    / "codex"
    / "scripts"
    / "record-bash.py"
)


def _write_shell_call_fixture(fixture_dir: Path, command: str) -> None:
    """Write a two-turn OpenAI v1-responses fixture sequence.

    turn-tool: the model issues a function_call(shell_command) for *command*
    turn-end:  the model returns a short text response
    """
    # --- turn-tool ---
    turn_tool_dir = fixture_dir / "turn-tool"
    turn_tool_dir.mkdir(parents=True)
    (turn_tool_dir / "meta.yaml").write_text(
        "id: turn-tool\nprovider: openai\nversion: v1-responses\nstatus: 200\n",
        encoding="utf-8",
    )
    arguments_str = json.dumps({"command": command})
    shell_item_in_progress = {
        "type": "function_call",
        "id": "fc_001",
        "call_id": "call_001",
        "name": "shell_command",
        "arguments": "",
        "status": "in_progress",
    }
    shell_item_done = {
        "type": "function_call",
        "id": "fc_001",
        "call_id": "call_001",
        "name": "shell_command",
        "arguments": arguments_str,
        "status": "completed",
    }
    turn_tool_events = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": {"id": "resp_tool", "status": "in_progress", "output": []},
        },
        {
            "type": "response.output_item.added",
            "sequence_number": 1,
            "output_index": 0,
            "item": shell_item_in_progress,
        },
        {
            "type": "response.function_call_arguments.delta",
            "sequence_number": 2,
            "item_id": "fc_001",
            "output_index": 0,
            "delta": arguments_str,
        },
        {
            "type": "response.function_call_arguments.done",
            "sequence_number": 3,
            "item_id": "fc_001",
            "output_index": 0,
            "arguments": arguments_str,
        },
        {
            "type": "response.output_item.done",
            "sequence_number": 4,
            "output_index": 0,
            "item": shell_item_done,
        },
        {
            "type": "response.completed",
            "sequence_number": 5,
            "response": {
                "id": "resp_tool",
                "status": "completed",
                "output": [shell_item_done],
            },
        },
    ]
    (turn_tool_dir / "response.json").write_text(
        json.dumps(turn_tool_events, indent=2), encoding="utf-8"
    )

    # --- turn-end ---
    turn_end_dir = fixture_dir / "turn-end"
    turn_end_dir.mkdir(parents=True)
    (turn_end_dir / "meta.yaml").write_text(
        "id: turn-end\nprovider: openai\nversion: v1-responses\nstatus: 200\n",
        encoding="utf-8",
    )
    msg_item = {
        "type": "message",
        "id": "turn_end_msg",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "done"}],
        "status": "completed",
    }
    turn_end_events = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": {"id": "resp_end", "status": "in_progress", "output": []},
        },
        {
            "type": "response.output_item.added",
            "sequence_number": 1,
            "output_index": 0,
            "item": {**msg_item, "content": [], "status": "in_progress"},
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 2,
            "item_id": "turn_end_msg",
            "output_index": 0,
            "content_index": 0,
            "delta": "done",
        },
        {
            "type": "response.output_text.done",
            "sequence_number": 3,
            "item_id": "turn_end_msg",
            "output_index": 0,
            "content_index": 0,
            "text": "done",
        },
        {
            "type": "response.output_item.done",
            "sequence_number": 4,
            "output_index": 0,
            "item": msg_item,
        },
        {
            "type": "response.completed",
            "sequence_number": 5,
            "response": {
                "id": "resp_end",
                "status": "completed",
                "output": [msg_item],
            },
        },
    ]
    (turn_end_dir / "response.json").write_text(
        json.dumps(turn_end_events, indent=2), encoding="utf-8"
    )

    # --- fixtures.yaml sequence ---
    (fixture_dir / "fixtures.yaml").write_text(
        "provider: openai\n"
        "version: v1-responses\n"
        "fixtures:\n"
        "  - expression: 'true'\n"
        "    sequence:\n"
        "      id: conversation\n"
        "      on_exhaust: last\n"
        "      steps: [turn-tool, turn-end]\n",
        encoding="utf-8",
    )


@unittest.skipUnless(
    _have("zolem") and _have("codex"),
    "zolem and codex must both be on PATH for the e2e hook test",
)
class CodexBashTelemetryHookE2ETest(E2ETestCase):
    """Verify the bento record-bash PostToolUse hook writes telemetry JSONL.

    Each test:
      1. Starts zolem on an OS-assigned port with a dynamic fixture that
         contains a function_call(shell_command) for a bento-attributed noop script.
      2. Creates a temp bento source repo with the noop script.
      3. Invokes ``codex exec`` with the zolem endpoint and bypass flags.
      4. Asserts the telemetry JSONL was written with expected fields.
    """

    PROVIDER = "openai"
    BACKEND = "fixture"

    def setUp(self) -> None:
        # Create temp fixture dir BEFORE calling super().setUp() so zolem
        # starts with the right fixtures directory.
        import tempfile
        self._fixture_tmp = tempfile.mkdtemp(prefix="bento-e2e-codex-fixtures-")
        self.FIXTURE_DIR = Path(self._fixture_tmp)
        # Create temp repo so we know the noop.py path before writing fixtures.
        import tempfile as _tmp
        self._repo_tmp = _tmp.mkdtemp(prefix="bento-e2e-codex-repo-")
        self._repo = Path(self._repo_tmp)
        self._setup_bento_source_repo(self._repo)
        self._noop_script = (
            self._repo / "catalog" / "skills" / "test-e2e" / "scripts" / "noop.py"
        )
        # Write fixtures with the known noop.py path.
        _write_shell_call_fixture(
            self.FIXTURE_DIR,
            f"python3 {self._noop_script}",
        )
        # State dir to capture telemetry output.
        import tempfile as _tmp2
        self._state_tmp = _tmp2.mkdtemp(prefix="bento-e2e-codex-state-")
        super().setUp()

    def tearDown(self) -> None:
        super().tearDown()
        shutil.rmtree(self._fixture_tmp, ignore_errors=True)
        shutil.rmtree(self._repo_tmp, ignore_errors=True)
        shutil.rmtree(self._state_tmp, ignore_errors=True)

    def _setup_bento_source_repo(self, repo: Path) -> None:
        """Set up *repo* as a bento source repo with a test noop script."""
        import subprocess
        def git(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=repo, check=True, capture_output=True
            )

        git("init", "-q", "-b", "main")
        git("config", "user.name", "E2E Test")
        git("config", "user.email", "e2e-test@example.com")
        (repo / "README.md").write_text("test\n", encoding="utf-8")
        git("add", "README.md")
        git("commit", "-q", "-m", "init")

        # Bento source-repo markers so bento_telemetry.attribute() recognises
        # scripts inside this repo.
        (repo / ".claude-plugin").mkdir()
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "bento"}) + "\n", encoding="utf-8"
        )
        plugin_meta = repo / "plugins" / "claude" / "bento" / ".claude-plugin"
        plugin_meta.mkdir(parents=True)
        (plugin_meta / "plugin.json").write_text(
            json.dumps({"name": "bento"}) + "\n", encoding="utf-8"
        )

        # A bento-attributed noop script whose path matches DEV_LAYOUT_RE:
        #   .../catalog/skills/<skill>/scripts/<script>
        script_dir = repo / "catalog" / "skills" / "test-e2e" / "scripts"
        script_dir.mkdir(parents=True)
        (script_dir / "noop.py").write_text(
            "# noop script for e2e telemetry test\n", encoding="utf-8"
        )

    # ----- tests ---------------------------------------------------------------

    def test_hook_records_bash_event(self) -> None:
        """codex executes a bento shell command → record-bash writes telemetry."""
        result = self._run_codex(
            self._repo,
            "say ok",
            extra_env={
                "XDG_STATE_HOME": self._state_tmp,
            },
        )

        # The telemetry hook writes to XDG_STATE_HOME/bento/telemetry/<UTC date>.jsonl
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl = Path(self._state_tmp) / "bento" / "telemetry" / f"{today}.jsonl"
        self.assertTrue(
            jsonl.exists(),
            msg=(
                f"telemetry JSONL not found: {jsonl}\n"
                f"codex stdout={result.stdout!r}\n"
                f"codex stderr={result.stderr!r}\n"
                f"zolem log:\n"
                + (self.zolem_log_path.read_text(errors="replace") if self.zolem_log_path.exists() else "")
            ),
        )

        lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreater(len(lines), 0, "JSONL file is empty")

        last = json.loads(lines[-1])
        self.assertEqual(last["kind"], "script")
        self.assertEqual(last["skill"], "test-e2e")
        self.assertEqual(last["script"], "noop.py")
        self.assertEqual(last["v"], 1)
        self.assertZolemHit()


if __name__ == "__main__":
    unittest.main()
