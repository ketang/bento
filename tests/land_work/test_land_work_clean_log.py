import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLEAN_LOG_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-clean-log.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


def commit_file(repo: Path, rel_path: str, content: str, message: str) -> None:
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(repo, "add", rel_path)
    git(repo, "commit", "-m", message)


class LandWorkCleanLogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.com")
        commit_file(self.repo, "README.md", "seed\n", "initial")
        git(self.repo, "checkout", "-b", "feature-x")

        commit_file(
            self.repo, ".launch-work/log.md", "v1\n",
            "chore(launch-work-log): worktree-ready",
        )
        commit_file(self.repo, "src/a.py", "a = 1\n", "feat: add a")
        commit_file(
            self.repo, ".launch-work/log.md", "v2\n",
            "chore(launch-work-log): tests-green",
        )
        commit_file(self.repo, "src/b.py", "b = 2\n", "feat: add b")
        commit_file(
            self.repo, ".launch-work/log.md", "v3\n",
            "chore(launch-work-log): ready-to-land",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_dry_run_lists_log_only_commits(self) -> None:
        result = run([str(CLEAN_LOG_SCRIPT), "--base", "main"], cwd=self.repo)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["log_only_commits"]), 3)
        self.assertEqual(payload["work_commits"], 2)
        self.assertFalse(payload["applied"])

    def test_apply_drops_log_commits_and_removes_file(self) -> None:
        result = run([str(CLEAN_LOG_SCRIPT), "--base", "main", "--apply"], cwd=self.repo)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["applied"])

        # All log-only commits are dropped, so the file is gone with them; no
        # separate deletion commit is needed in the rebase path.
        self.assertFalse((self.repo / ".launch-work/log.md").exists())

        log = git(self.repo, "log", "main..HEAD", "--format=%s").stdout.strip().splitlines()
        for msg in (
            "chore(launch-work-log): worktree-ready",
            "chore(launch-work-log): tests-green",
            "chore(launch-work-log): ready-to-land",
        ):
            self.assertNotIn(msg, log)
        self.assertEqual(sum(1 for line in log if line.startswith("feat:")), 2)

    def test_keep_commits_skips_rebase_but_still_deletes(self) -> None:
        result = run(
            [str(CLEAN_LOG_SCRIPT), "--base", "main", "--apply", "--keep-commits"],
            cwd=self.repo,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["applied"])
        self.assertTrue(payload["kept_log_commits"])

        self.assertFalse((self.repo / ".launch-work/log.md").exists())
        log = git(self.repo, "log", "main..HEAD", "--format=%s").stdout.strip().splitlines()
        self.assertIn("chore(launch-work-log): worktree-ready", log)
        self.assertIn("chore(launch-work-log): ready-to-land", log)
        self.assertIn("chore(launch-work-log): remove", log)


if __name__ == "__main__":
    unittest.main()
