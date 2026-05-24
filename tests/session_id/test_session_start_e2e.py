"""Hermetic zolem-backed e2e test for the session-start SessionStart hook."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.e2e_utils import E2ETestCase, _have

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO_ROOT / "catalog" / "hooks" / "session-id" / "claude" / "scripts" / "session-start.py"


@unittest.skipUnless(_have("zolem") and _have("claude"), "zolem and claude must both be on PATH")
class SessionStartHookE2ETest(E2ETestCase):
    BACKEND = "lorem"
    FIXTURE_NS = None

    def setUp(self) -> None:
        super().setUp()
        # Create isolated HOME and TMPDIR under the test's temp root
        self.temp_home = self.root / "home"
        self.temp_tmp = self.root / "tmp"
        self.temp_home.mkdir()
        self.temp_tmp.mkdir()

    def _init_repo_with_hook(self) -> Path:
        repo = self._init_repo()
        settings_dir = repo / ".claude"
        settings_dir.mkdir()
        settings = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {"type": "command", "command": str(HOOK_SCRIPT)}
                        ]
                    }
                ]
            }
        }
        (settings_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        return repo

    def test_hook_writes_session_id(self) -> None:
        repo = self._init_repo_with_hook()
        self._run_claude(repo, "say ok", extra_env={"HOME": str(self.temp_home), "TMPDIR": str(self.temp_tmp)})
        session_id_file = self.temp_home / ".claude" / "session_id"
        self.assertTrue(session_id_file.exists(), "session_id file not written by hook")
        content = session_id_file.read_text(encoding="utf-8").strip()
        self.assertGreater(len(content), 0, "session_id file is empty")

    def test_hook_creates_scratch_directory(self) -> None:
        repo = self._init_repo_with_hook()
        self._run_claude(repo, "say ok", extra_env={"HOME": str(self.temp_home), "TMPDIR": str(self.temp_tmp)})
        session_id_file = self.temp_home / ".claude" / "session_id"
        self.assertTrue(session_id_file.exists(), "session_id file not written by hook")
        session_id = session_id_file.read_text(encoding="utf-8").strip()
        scratch = self.temp_tmp / f"claude-session-{session_id}"
        self.assertTrue(scratch.is_dir(), f"scratch dir not created: {scratch}")


if __name__ == "__main__":
    unittest.main()
