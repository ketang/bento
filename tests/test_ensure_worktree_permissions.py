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
    / "ensure-worktree-permissions.py"
)
DEFAULT_WORKTREE_ROOT = str(Path.home() / ".local" / "share" / "worktrees")


class EnsureWorktreePermissionsHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.fake_home = self.tmp_path / "home"
        self.fake_home.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _settings_path(self) -> Path:
        return self.fake_home / ".claude" / "settings.json"

    def _write_settings(self, payload: dict) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _read_settings(self) -> dict:
        path = self._settings_path()
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _run(self, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(self.fake_home)
        return subprocess.run(
            [str(HOOK_SCRIPT)],
            input=json.dumps({"session_id": "abc"}),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(cwd) if cwd else str(self.tmp_path),
        )

    def _list_dirs(self) -> list[str]:
        return self._read_settings().get("permissions", {}).get("additionalDirectories", [])

    def test_creates_settings_with_default_root(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(DEFAULT_WORKTREE_ROOT, self._list_dirs())

    def test_idempotent(self) -> None:
        self._run()
        first = self._read_settings()
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self._read_settings(), first)

    def test_preserves_existing_unrelated_settings(self) -> None:
        self._write_settings({
            "model": "opus",
            "permissions": {
                "additionalDirectories": ["/some/other/dir"],
                "allow": ["Bash(ls:*)"],
            },
        })
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        settings = self._read_settings()
        self.assertEqual(settings["model"], "opus")
        self.assertIn("/some/other/dir", settings["permissions"]["additionalDirectories"])
        self.assertIn(DEFAULT_WORKTREE_ROOT, settings["permissions"]["additionalDirectories"])
        self.assertEqual(settings["permissions"]["allow"], ["Bash(ls:*)"])

    def test_skips_when_already_covered_by_parent(self) -> None:
        parent = str(Path.home())
        self._write_settings({"permissions": {"additionalDirectories": [parent]}})
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self._list_dirs(), [parent])

    def test_malformed_settings_is_silent_no_op(self) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), "{not valid json")

    def test_observes_existing_worktrees_in_repo(self) -> None:
        repo = self.tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init", "--no-gpg-sign"], check=True, env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"})
        observed_root = self.tmp_path / "elsewhere"
        observed_root.mkdir()
        worktree_path = observed_root / "feature"
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-b", "feature", str(worktree_path)],
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"},
        )
        result = self._run(cwd=repo)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        dirs = self._list_dirs()
        self.assertIn(str(observed_root), dirs)
        self.assertIn(DEFAULT_WORKTREE_ROOT, dirs)

    def test_non_git_cwd_only_adds_default(self) -> None:
        non_git = self.tmp_path / "plain"
        non_git.mkdir()
        result = self._run(cwd=non_git)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self._list_dirs(), [DEFAULT_WORKTREE_ROOT])


if __name__ == "__main__":
    unittest.main()
