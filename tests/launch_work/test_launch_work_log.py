import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_SCRIPT = REPO_ROOT / "catalog/skills/launch-work/scripts/launch-work-log.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


def init_feature_repo(parent: Path, name: str = "repo") -> Path:
    repo = parent / name
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    git(repo, "checkout", "-b", "feature-x")
    return repo


class LaunchWorkLogInitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = init_feature_repo(Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_init_creates_log_with_header_and_commits(self) -> None:
        result = run([str(LOG_SCRIPT), "init"], cwd=self.repo)
        payload = json.loads(result.stdout)
        log_path = self.repo / ".launch-work" / "log.md"

        self.assertTrue(log_path.is_file())
        self.assertEqual(payload["path"], str(log_path))
        self.assertEqual(payload["checkpoint"], "worktree-ready")

        body = log_path.read_text(encoding="utf-8")
        self.assertIn("checkpoint: worktree-ready", body)
        self.assertRegex(body, r"last-updated: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
        self.assertIn("## Next action", body)

        log_msg = git(self.repo, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(log_msg, "chore(launch-work-log): worktree-ready")

    def test_init_refuses_when_log_already_exists(self) -> None:
        run([str(LOG_SCRIPT), "init"], cwd=self.repo)
        result = run([str(LOG_SCRIPT), "init"], cwd=self.repo, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    def test_init_refuses_on_primary_branch(self) -> None:
        git(self.repo, "checkout", "main")
        result = run([str(LOG_SCRIPT), "init"], cwd=self.repo, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("primary branch", result.stderr)


if __name__ == "__main__":
    unittest.main()
