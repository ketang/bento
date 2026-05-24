import importlib.machinery
import importlib.util
import json
import os
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
    / "register-require-worktree-hook.py"
)


def load_module():
    loader = importlib.machinery.SourceFileLoader("register_require_worktree_hook", str(SCRIPT))
    spec = importlib.util.spec_from_loader("register_require_worktree_hook", loader)
    if spec is None:
        raise RuntimeError("unable to load register-require-worktree-hook")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RegisterRequireWorktreeHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.fake_home = self.root / "home"
        self.fake_home.mkdir()
        self.plugin_root = self.root / "plugin"
        (self.plugin_root / "hooks" / "scripts").mkdir(parents=True)
        (self.plugin_root / "hooks" / "scripts" / "require-worktree.sh").write_text(
            "#!/bin/sh\n",
            encoding="utf-8",
        )
        self.module = load_module()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _settings_path(self) -> Path:
        return self.fake_home / ".claude" / "settings.json"

    def _write_settings(self, payload: dict) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _read_settings(self) -> dict:
        return json.loads(self._settings_path().read_text(encoding="utf-8"))

    def _run(self) -> int:
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.fake_home)
        try:
            return self.module.main(
                ["register-require-worktree-hook.py", str(self.plugin_root)]
            )
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

    def test_registers_all_edit_tools(self) -> None:
        self.assertEqual(self._run(), 0)

        settings = self._read_settings()
        pre_tool_use = settings["hooks"]["PreToolUse"]
        by_matcher = {entry["matcher"]: entry for entry in pre_tool_use}
        for matcher in ("Edit", "Write", "NotebookEdit"):
            command = by_matcher[matcher]["hooks"][0]["command"]
            self.assertEqual(
                command,
                f"{self.plugin_root}/hooks/scripts/require-worktree.sh",
            )

    def test_preserves_existing_settings_and_hooks(self) -> None:
        self._write_settings(
            {
                "model": "opus",
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "existing-command",
                                }
                            ],
                        }
                    ]
                },
            }
        )

        self.assertEqual(self._run(), 0)

        settings = self._read_settings()
        self.assertEqual(settings["model"], "opus")
        commands = [
            hook["command"]
            for entry in settings["hooks"]["PreToolUse"]
            for hook in entry["hooks"]
        ]
        self.assertIn("existing-command", commands)
        self.assertIn(f"{self.plugin_root}/hooks/scripts/require-worktree.sh", commands)

    def test_idempotent(self) -> None:
        self._run()
        first = self._settings_path().read_text(encoding="utf-8")

        self._run()

        self.assertEqual(self._settings_path().read_text(encoding="utf-8"), first)

    def test_evicts_stale_versioned_entries(self) -> None:
        stale_command_50 = (
            "/home/u/.claude/plugins/cache/bento/bento/1.0.50/hooks/scripts/require-worktree.sh"
        )
        stale_command_51 = (
            "/home/u/.claude/plugins/cache/bento/bento/1.0.51/hooks/scripts/require-worktree.sh"
        )
        self._write_settings(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit",
                            "hooks": [{"type": "command", "command": stale_command_50}],
                        },
                        {
                            "matcher": "Edit",
                            "hooks": [{"type": "command", "command": stale_command_51}],
                        },
                        {
                            "matcher": "Write",
                            "hooks": [{"type": "command", "command": stale_command_50}],
                        },
                        {
                            "matcher": "NotebookEdit",
                            "hooks": [{"type": "command", "command": stale_command_51}],
                        },
                    ]
                }
            }
        )

        self.assertEqual(self._run(), 0)

        settings = self._read_settings()
        pre_tool_use = settings["hooks"]["PreToolUse"]
        current = f"{self.plugin_root}/hooks/scripts/require-worktree.sh"

        # No stale entries remain
        commands = [
            hook["command"]
            for entry in pre_tool_use
            for hook in entry["hooks"]
        ]
        self.assertNotIn(stale_command_50, commands)
        self.assertNotIn(stale_command_51, commands)

        # Exactly one current-version entry per matcher
        by_matcher: dict[str, list[dict]] = {}
        for entry in pre_tool_use:
            by_matcher.setdefault(entry["matcher"], []).append(entry)
        for matcher in ("Edit", "Write", "NotebookEdit"):
            self.assertEqual(len(by_matcher[matcher]), 1)
            self.assertEqual(by_matcher[matcher][0]["hooks"][0]["command"], current)

    def test_does_not_evict_other_plugins(self) -> None:
        other_plugin_command = (
            "/home/u/.claude/plugins/cache/some-other-plugin/scripts/require-worktree.sh"
        )
        self._write_settings(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit",
                            "hooks": [
                                {"type": "command", "command": other_plugin_command}
                            ],
                        }
                    ]
                }
            }
        )

        self.assertEqual(self._run(), 0)

        commands = [
            hook["command"]
            for entry in self._read_settings()["hooks"]["PreToolUse"]
            for hook in entry["hooks"]
        ]
        self.assertIn(other_plugin_command, commands)
        self.assertIn(
            f"{self.plugin_root}/hooks/scripts/require-worktree.sh", commands
        )

    def test_malformed_settings_is_silent_no_op(self) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")

        self.assertEqual(self._run(), 0)
        self.assertEqual(path.read_text(encoding="utf-8"), "{not json")


if __name__ == "__main__":
    unittest.main()
