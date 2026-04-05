import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog" / "hooks" / "session-id" / "scripts" / "session-start.py"


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


if __name__ == "__main__":
    unittest.main()
