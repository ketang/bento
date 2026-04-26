import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DISCOVER_SCRIPT = REPO_ROOT / "catalog/skills/launch-work/scripts/launch-work-discover.py"
LOG_SCRIPT = REPO_ROOT / "catalog/skills/launch-work/scripts/launch-work-log.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


class LaunchWorkDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.com")
        (self.repo / "README.md").write_text("seed\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_worktree_with_log(self, branch: str) -> Path:
        wt = self.root / branch
        git(self.repo, "worktree", "add", "-b", branch, str(wt), "main")
        # Configure user identity inside the worktree (inherits the repo config
        # in current Git, but be explicit so the test is robust).
        git(wt, "config", "user.name", "Test")
        git(wt, "config", "user.email", "test@example.com")
        run([str(LOG_SCRIPT), "init"], cwd=wt)
        return wt

    def test_discover_lists_worktrees_with_logs(self) -> None:
        wt_a = self._make_worktree_with_log("feature-a")
        wt_b = self._make_worktree_with_log("feature-b")

        result = run([str(DISCOVER_SCRIPT)], cwd=self.repo)
        payload = json.loads(result.stdout)

        branches = {entry["branch"]: entry for entry in payload["logs"]}
        self.assertIn("feature-a", branches)
        self.assertIn("feature-b", branches)
        self.assertEqual(branches["feature-a"]["checkpoint"], "worktree-ready")
        self.assertEqual(branches["feature-a"]["worktree"], str(wt_a))
        self.assertEqual(branches["feature-b"]["worktree"], str(wt_b))

    def test_discover_skips_worktrees_without_logs(self) -> None:
        plain_wt = self.root / "plain"
        git(self.repo, "worktree", "add", "-b", "plain", str(plain_wt), "main")

        self._make_worktree_with_log("feature-x")

        result = run([str(DISCOVER_SCRIPT)], cwd=self.repo)
        payload = json.loads(result.stdout)
        branches = {entry["branch"] for entry in payload["logs"]}
        self.assertEqual(branches, {"feature-x"})

    def test_discover_emits_empty_list_when_no_logs(self) -> None:
        result = run([str(DISCOVER_SCRIPT)], cwd=self.repo)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["logs"], [])


if __name__ == "__main__":
    unittest.main()
