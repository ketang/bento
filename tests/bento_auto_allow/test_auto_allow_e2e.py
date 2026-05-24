"""End-to-end tests for the auto-allow PreToolUse hook using zolem fixtures."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from tests.e2e_utils import E2ETestCase, FIXTURES_BASE, _have

REPO_ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(
    _have("zolem") and _have("claude"), "zolem and claude must both be on PATH"
)
class AutoAllowHookE2ETest(E2ETestCase):
    BACKEND = "fixture"
    FIXTURE_NS = "e2e-auto-allow"

    def setUp(self) -> None:
        # Create a temp copy of the fixture dir so we can substitute
        # SENTINEL_PLACEHOLDER per test before zolem starts.
        self._fixture_tmp = tempfile.TemporaryDirectory()
        fixture_src = FIXTURES_BASE / "e2e-auto-allow"
        self._fixture_dir = Path(self._fixture_tmp.name) / "e2e-auto-allow"
        shutil.copytree(fixture_src, self._fixture_dir)

        # Plugin root with scripts/foo.py
        self._plugin_root = Path(self._fixture_tmp.name) / "plugin"
        scripts_dir = self._plugin_root / "scripts"
        scripts_dir.mkdir(parents=True)
        foo_py = scripts_dir / "foo.py"
        foo_py.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "pathlib.Path(sys.argv[1]).write_text('ok')\n",
            encoding="utf-8",
        )
        foo_py.chmod(0o755)

        # Monkey-patch FIXTURES_BASE so the base class starts zolem with
        # our temp copy.
        import tests.e2e_utils as _mod

        self._orig_fixtures_base = _mod.FIXTURES_BASE
        _mod.FIXTURES_BASE = Path(self._fixture_tmp.name)

        # Don't call super().setUp() yet — subclasses patch the fixture first
        # via _patch_and_start().

    def _patch_and_start(self, command: str) -> None:
        """Substitute SENTINEL_PLACEHOLDER in turn-tool/response.json, then
        start zolem via the base class setUp."""
        resp = self._fixture_dir / "turn-tool" / "response.json"
        orig = self._orig_fixtures_base / "e2e-auto-allow" / "turn-tool" / "response.json"
        text = orig.read_text(encoding="utf-8")
        text = text.replace("SENTINEL_PLACEHOLDER", command)
        resp.write_text(text, encoding="utf-8")
        super().setUp()

    def tearDown(self) -> None:
        # super().tearDown() expects attributes set by super().setUp(),
        # which only runs inside _patch_and_start.
        if hasattr(self, "zolem"):
            super().tearDown()
        import tests.e2e_utils as _mod

        _mod.FIXTURES_BASE = self._orig_fixtures_base
        self._fixture_tmp.cleanup()

    def _init_repo_with_hook(self, plugin_root: Path) -> Path:
        repo = self._init_repo()
        hook_script = (
            REPO_ROOT
            / "catalog"
            / "hooks"
            / "bento"
            / "claude"
            / "scripts"
            / "auto-allow.py"
        )
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"python3 {hook_script} bento {plugin_root}",
                            }
                        ],
                    }
                ]
            }
        }
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.json").write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )
        return repo

    def test_allows_plugin_script(self) -> None:
        sentinel = Path(self._fixture_tmp.name) / "sentinel-allow"
        foo_py = self._plugin_root / "scripts" / "foo.py"
        self._patch_and_start(f"python3 {foo_py} {sentinel}")

        repo = self._init_repo_with_hook(self._plugin_root)
        result = self._run_claude(repo, prompt="run the script")
        self.assertTrue(
            sentinel.exists(),
            f"Sentinel not created; hook should have auto-allowed.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}",
        )

    def test_blocks_outside_plugin(self) -> None:
        evil_script = Path(self._fixture_tmp.name) / f"evil-e2e-{uuid.uuid4()}.py"
        evil_script.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "pathlib.Path(sys.argv[1]).write_text('pwned')\n",
            encoding="utf-8",
        )
        evil_script.chmod(0o755)
        sentinel = Path(self._fixture_tmp.name) / "evil-sentinel"
        self._patch_and_start(f"python3 {evil_script} {sentinel}")

        repo = self._init_repo_with_hook(self._plugin_root)
        self._run_claude(repo, prompt="run the script")
        self.assertFalse(
            sentinel.exists(),
            "Sentinel was created; hook should have blocked the outside script.",
        )


if __name__ == "__main__":
    unittest.main()
