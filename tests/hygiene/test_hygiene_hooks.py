import importlib.machinery
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "catalog" / "hooks" / "hygiene" / "claude" / "scripts"
BASELINE_SCRIPT = HOOKS_DIR / "hygiene-baseline.py"
CHECK_SCRIPT = HOOKS_DIR / "hygiene-check.py"


def load_module(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


class HygieneHooksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.cache = self.root / "cache"
        self.home.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "README.md").write_text("hello\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "init")

        self.baseline = load_module("hygiene_baseline", BASELINE_SCRIPT)
        self.check = load_module("hygiene_check", CHECK_SCRIPT)
        self.env = {"XDG_CACHE_HOME": str(self.cache)}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _hook_input(self, **overrides) -> dict:
        payload = {"session_id": "sess1", "cwd": str(self.repo)}
        payload.update(overrides)
        return payload

    def _snapshot(self, **overrides) -> None:
        self.baseline.run(self._hook_input(**overrides), home=self.home, env=self.env)

    def _evaluate(self, **overrides):
        return self.check.evaluate(self._hook_input(**overrides), home=self.home, env=self.env)

    # --- baseline -----------------------------------------------------------

    def test_baseline_written_to_cache(self) -> None:
        self._snapshot()
        path = self.cache / "bento" / "hygiene-baseline-sess1.txt"
        self.assertTrue(path.exists())

    def test_baseline_records_existing_untracked_files(self) -> None:
        (self.repo / "preexisting.txt").write_text("x\n", encoding="utf-8")
        self._snapshot()
        path = self.cache / "bento" / "hygiene-baseline-sess1.txt"
        self.assertIn("preexisting.txt", path.read_text(encoding="utf-8").splitlines())

    def test_baseline_no_op_for_invalid_session_id(self) -> None:
        self.baseline.run({"session_id": "../x", "cwd": str(self.repo)}, home=self.home, env=self.env)
        self.assertFalse((self.cache / "bento").exists())

    def test_baseline_no_op_outside_git_repo(self) -> None:
        nongit = self.root / "plain"
        nongit.mkdir()
        self.baseline.run({"session_id": "sess1", "cwd": str(nongit)}, home=self.home, env=self.env)
        self.assertFalse((self.cache / "bento" / "hygiene-baseline-sess1.txt").exists())

    # --- check: acceptance criteria ----------------------------------------

    def test_new_stray_file_warns_and_names_it(self) -> None:
        self._snapshot()
        (self.repo / "fuzz-output.log").write_text("junk\n", encoding="utf-8")
        decision = self._evaluate()
        self.assertIsNotNone(decision)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("fuzz-output.log", decision["reason"])

    def test_no_warning_when_tree_unchanged(self) -> None:
        self._snapshot()
        self.assertIsNone(self._evaluate())

    def test_gitignored_file_does_not_warn(self) -> None:
        (self.repo / ".gitignore").write_text("*.bin\n", encoding="utf-8")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-m", "ignore")
        self._snapshot()
        (self.repo / "build.bin").write_text("0" * 100, encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_suppression_flag_silences_warning(self) -> None:
        self._snapshot()
        (self.repo / "stray.txt").write_text("junk\n", encoding="utf-8")
        (self.repo / ".agent-mode.local").write_text("hygiene_check=false\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_unrelated_agent_mode_key_does_not_suppress(self) -> None:
        self._snapshot()
        (self.repo / "stray.txt").write_text("junk\n", encoding="utf-8")
        (self.repo / ".agent-mode.local").write_text("require_worktree=false\n", encoding="utf-8")
        self.assertIsNotNone(self._evaluate())

    def test_stop_hook_active_avoids_reblock(self) -> None:
        self._snapshot()
        (self.repo / "stray.txt").write_text("junk\n", encoding="utf-8")
        self.assertIsNone(self._evaluate(stop_hook_active=True))

    def test_no_baseline_stays_silent(self) -> None:
        # No snapshot taken (e.g. resumed session).
        (self.repo / "stray.txt").write_text("junk\n", encoding="utf-8")
        self.assertIsNone(self._evaluate())

    def test_preexisting_untracked_file_is_not_flagged(self) -> None:
        (self.repo / "preexisting.txt").write_text("x\n", encoding="utf-8")
        self._snapshot()
        # Only a genuinely new file should be reported.
        (self.repo / "new.txt").write_text("y\n", encoding="utf-8")
        decision = self._evaluate()
        self.assertIsNotNone(decision)
        self.assertIn("new.txt", decision["reason"])
        self.assertNotIn("preexisting.txt", decision["reason"])


if __name__ == "__main__":
    unittest.main()
