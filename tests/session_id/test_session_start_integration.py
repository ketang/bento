"""Integration test: verifies the SessionStart hook fires and produces the
expected side effects when Claude Code starts a session.

Requires a live Claude Code installation and an active `claude login` session.
Skipped by default; opt in with BENTO_INTEGRATION_TESTS=1.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO_ROOT / "catalog" / "hooks" / "session-id" / "scripts" / "session-start.py"

SKIP_REASON = "set BENTO_INTEGRATION_TESTS=1 to run"


@unittest.skipUnless(os.environ.get("BENTO_INTEGRATION_TESTS"), SKIP_REASON)
class SessionStartIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        settings = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": str(HOOK_SCRIPT),
                            }
                        ]
                    }
                ]
            }
        }
        self.settings_file = Path(self.temp.name) / "settings.json"
        self.settings_file.write_text(json.dumps(settings), encoding="utf-8")
        self.scratch_dirs: list[Path] = []

    def tearDown(self) -> None:
        for d in self.scratch_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self.temp.cleanup()

    def _run(self, extra_args: list[str] | None = None, prompt: str = "say ok") -> dict:
        """Run claude -p and return the parsed JSON result."""
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--settings", str(self.settings_file)]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(
            result.returncode, 0,
            msg=f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        return json.loads(result.stdout)

    def _session_id_file(self) -> Path:
        return Path.home() / ".claude" / "session_id"

    def _register_scratch(self, session_id: str) -> Path:
        d = Path(f"/tmp/claude-session-{session_id}")
        self.scratch_dirs.append(d)
        return d

    def test_hook_writes_session_id_matching_claude_output(self) -> None:
        before = time.time()
        output = self._run()

        claude_session_id = output["session_id"]
        self._register_scratch(claude_session_id)

        session_id_file = self._session_id_file()
        self.assertTrue(session_id_file.exists(), "session_id file not written by hook")
        self.assertGreater(session_id_file.stat().st_mtime, before, "session_id file not updated this run")
        written_id = session_id_file.read_text(encoding="utf-8").strip()
        self.assertEqual(written_id, claude_session_id, "file session_id does not match Claude's session_id")

    def test_hook_creates_scratch_directory(self) -> None:
        output = self._run()
        scratch = self._register_scratch(output["session_id"])
        self.assertTrue(scratch.is_dir(), f"scratch dir not created: {scratch}")

    def test_session_id_stable_across_context_reset(self) -> None:
        output = self._run()
        session_id = output["session_id"]
        scratch = self._register_scratch(session_id)

        time.sleep(1)  # ensure mtime advances past the first run
        before_reset = time.time()

        self._run(extra_args=["--resume", session_id], prompt="/reset")

        written_after = self._session_id_file().read_text(encoding="utf-8").strip()
        self.assertEqual(written_after, session_id, "session_id changed after /reset")
        self.assertGreater(self._session_id_file().stat().st_mtime, before_reset, "hook did not re-fire after /reset")
        self.assertTrue(scratch.is_dir(), "scratch dir gone after /reset")

    def test_session_id_stable_across_resume(self) -> None:
        output = self._run()
        session_id = output["session_id"]
        scratch = self._register_scratch(session_id)

        time.sleep(1)  # ensure mtime advances past the first run
        before_resume = time.time()

        resumed = self._run(extra_args=["--resume", session_id])
        self.assertEqual(resumed["session_id"], session_id, "session_id changed after --resume")

        written_after = self._session_id_file().read_text(encoding="utf-8").strip()
        self.assertEqual(written_after, session_id, "file session_id changed after --resume")
        self.assertGreater(self._session_id_file().stat().st_mtime, before_resume, "hook did not re-fire on resume")
        self.assertTrue(scratch.is_dir(), "scratch dir gone after resume")


if __name__ == "__main__":
    unittest.main()
