import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_SCRIPT = REPO_ROOT / "catalog" / "skills" / "handoff" / "scripts" / "handoff.py"


class HandoffHelpTest(unittest.TestCase):
    def test_help_flag_exits_zero_and_describes_inputs(self) -> None:
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--input", result.stdout)
        self.assertIn("--slug", result.stdout)
        self.assertIn("--verbose", result.stdout)


class HandoffPreconditionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.input_path = self.tmp_path / "body.md"
        self.input_path.write_text("# body\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, cwd: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path), *extra],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_not_in_git_repo_emits_diagnostic_and_writes_no_file(self) -> None:
        non_repo = self.tmp_path / "not-a-repo"
        non_repo.mkdir()
        result = self._run(non_repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not in a git repository", result.stderr)
        self.assertEqual(list((non_repo).iterdir()), [])

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    def _make_repo_with_commit(self) -> Path:
        repo = self.tmp_path / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("hi\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def test_active_expedition_emits_diagnostic_and_writes_no_file(self) -> None:
        repo = self._make_repo_with_commit()
        # Stub expedition.py via env override so the helper sees an "active" expedition.
        fake_expedition = self.tmp_path / "fake-expedition.py"
        fake_expedition.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "if 'discover' in sys.argv:\n"
            "    cwd = os.getcwd()\n"
            "    json.dump({'ok': True, 'expeditions': [{\n"
            "        'expedition': 'demo',\n"
            "        'base_worktree': cwd,\n"
            "        'active_branches': [],\n"
            "        'current_checkout': True,\n"
            "    }]}, sys.stdout)\n"
            "    sys.stdout.write('\\n')\n",
            encoding="utf-8",
        )
        fake_expedition.chmod(0o755)
        env = os.environ.copy()
        env["BENTO_EXPEDITION_SCRIPT"] = str(fake_expedition)
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path)],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active expedition", result.stderr)
        self.assertIn("demo", result.stderr)

    def test_detached_head_emits_diagnostic_and_writes_no_file(self) -> None:
        repo = self._make_repo_with_commit()
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._git(repo, "checkout", "-q", "--detach", sha)
        existing_before = set(p.name for p in repo.iterdir())
        result = self._run(repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD is detached", result.stderr)
        existing_after = set(p.name for p in repo.iterdir())
        self.assertEqual(existing_before, existing_after)


if __name__ == "__main__":
    unittest.main()
