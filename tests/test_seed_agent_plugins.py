import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "bento"
    / "scripts"
    / "seed-agent-plugins.py"
)


class SeedAgentPluginsHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_fake_plugin_root(self) -> Path:
        plugin_root = self.tmp_path / "plugin"
        bundled = (
            plugin_root
            / "skills"
            / "handoff"
            / "references"
            / "templates"
            / "handoff.md"
        )
        bundled.parent.mkdir(parents=True)
        bundled.write_text("BUNDLED\n", encoding="utf-8")
        return plugin_root

    def _run(self, plugin_root: Path, *, xdg: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(xdg)
        return subprocess.run(
            [str(HOOK_SCRIPT), str(plugin_root)],
            input=json.dumps({"session_id": "abc"}),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_first_run_creates_home_scope_template(self) -> None:
        plugin_root = self._make_fake_plugin_root()
        xdg = self.tmp_path / "xdg"
        target = xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        self.assertFalse(target.exists())
        result = self._run(plugin_root, xdg=xdg)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "BUNDLED\n")

    def test_second_run_does_not_overwrite(self) -> None:
        plugin_root = self._make_fake_plugin_root()
        xdg = self.tmp_path / "xdg"
        target = xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        target.parent.mkdir(parents=True)
        target.write_text("USER EDITED\n", encoding="utf-8")
        before = target.stat().st_mtime_ns
        result = self._run(plugin_root, xdg=xdg)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "USER EDITED\n")
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_missing_bundled_default_no_ops_silently(self) -> None:
        plugin_root = self.tmp_path / "empty-plugin"
        plugin_root.mkdir()
        xdg = self.tmp_path / "xdg"
        result = self._run(plugin_root, xdg=xdg)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        target = (
            xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        )
        self.assertFalse(target.exists())

    def test_unwritable_xdg_no_ops_silently(self) -> None:
        plugin_root = self._make_fake_plugin_root()
        xdg = self.tmp_path / "xdg"
        xdg.mkdir()
        os.chmod(xdg, 0o500)
        try:
            result = self._run(plugin_root, xdg=xdg)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
        finally:
            os.chmod(xdg, 0o700)


if __name__ == "__main__":
    unittest.main()
