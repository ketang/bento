import importlib.machinery
import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "session-id"
    / "claude"
    / "scripts"
    / "session-start.py"
)


def load_session_start():
    loader = importlib.machinery.SourceFileLoader("session_start", str(SCRIPT))
    spec = importlib.util.spec_from_loader("session_start", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class SessionStartTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.tmp = self.root / "tmp"
        self.home.mkdir()
        self.tmp.mkdir()
        self.module = load_session_start()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_writes_session_id_file(self) -> None:
        self.module.run({"session_id": "abc123"}, home=self.home, tmp=self.tmp)
        written = (self.home / ".claude" / "session_id").read_text(encoding="utf-8")
        self.assertEqual(written.strip(), "abc123")

    def test_creates_scratch_directory(self) -> None:
        self.module.run({"session_id": "abc123"}, home=self.home, tmp=self.tmp)
        self.assertTrue((self.tmp / "claude-session-abc123").is_dir())

    def test_no_op_when_session_id_missing(self) -> None:
        self.module.run({}, home=self.home, tmp=self.tmp)
        self.assertFalse((self.home / ".claude" / "session_id").exists())

    def test_no_op_when_session_id_empty(self) -> None:
        self.module.run({"session_id": ""}, home=self.home, tmp=self.tmp)
        self.assertFalse((self.home / ".claude" / "session_id").exists())

    def test_overwrites_session_id_on_resume(self) -> None:
        self.module.run({"session_id": "first"}, home=self.home, tmp=self.tmp)
        self.module.run({"session_id": "second"}, home=self.home, tmp=self.tmp)
        written = (self.home / ".claude" / "session_id").read_text(encoding="utf-8")
        self.assertEqual(written.strip(), "second")

    def test_idempotent_when_scratch_dir_already_exists(self) -> None:
        self.module.run({"session_id": "abc123"}, home=self.home, tmp=self.tmp)
        self.module.run({"session_id": "abc123"}, home=self.home, tmp=self.tmp)
        self.assertTrue((self.tmp / "claude-session-abc123").is_dir())

    def test_rejects_session_id_with_path_separators(self) -> None:
        self.module.run({"session_id": "../escape"}, home=self.home, tmp=self.tmp)
        self.assertFalse((self.home / ".claude" / "session_id").exists())
        # Nothing should be created outside the scratch root.
        self.assertFalse((self.root / "escape").exists())

    def test_rejects_session_id_with_slash(self) -> None:
        self.module.run({"session_id": "a/b"}, home=self.home, tmp=self.tmp)
        self.assertFalse((self.home / ".claude" / "session_id").exists())

    def test_prunes_stale_scratch_dirs(self) -> None:
        stale = self.tmp / "claude-session-old"
        stale.mkdir()
        old_time = time.time() - 8 * 86400
        os.utime(stale, (old_time, old_time))
        self.module.run({"session_id": "fresh"}, home=self.home, tmp=self.tmp)
        self.assertFalse(stale.exists(), "stale scratch dir was not pruned")
        self.assertTrue((self.tmp / "claude-session-fresh").is_dir())

    def test_keeps_recent_scratch_dirs(self) -> None:
        recent = self.tmp / "claude-session-recent"
        recent.mkdir()
        self.module.run({"session_id": "fresh"}, home=self.home, tmp=self.tmp)
        self.assertTrue(recent.is_dir(), "recent scratch dir should be kept")

    def test_prune_ignores_unrelated_dirs(self) -> None:
        unrelated = self.tmp / "some-other-dir"
        unrelated.mkdir()
        old_time = time.time() - 30 * 86400
        os.utime(unrelated, (old_time, old_time))
        self.module.run({"session_id": "fresh"}, home=self.home, tmp=self.tmp)
        self.assertTrue(unrelated.is_dir(), "non-scratch dirs must not be pruned")

    def test_default_path_honors_home_and_tmpdir_env(self) -> None:
        # Exercise run() with no dependency injection: it must resolve HOME via
        # Path.home() and the scratch root via tempfile.gettempdir() (TMPDIR).
        env = {"HOME": str(self.home), "TMPDIR": str(self.tmp)}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        # tempfile caches the resolved tmpdir; clear it so TMPDIR takes effect.
        tempfile.tempdir = None
        try:
            self.module.run({"session_id": "envcheck"})
        finally:
            tempfile.tempdir = None
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(
            (self.home / ".claude" / "session_id").read_text(encoding="utf-8").strip(),
            "envcheck",
        )
        self.assertTrue((self.tmp / "claude-session-envcheck").is_dir())


if __name__ == "__main__":
    unittest.main()
