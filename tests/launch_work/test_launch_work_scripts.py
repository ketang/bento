import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCRIPT = REPO_ROOT / "catalog/skills/launch-work/scripts/launch-work-bootstrap.py"
VERIFY_SCRIPT = REPO_ROOT / "catalog/skills/launch-work/scripts/launch-work-verify.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


class LaunchWorkScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Launch Work Test")
        git(self.repo, "config", "user.email", "launch-work@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_bootstrap(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(BOOTSTRAP_SCRIPT), *args], cwd or self.repo, check=check)

    def run_verify(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(VERIFY_SCRIPT), *args], cwd, check=check)

    def test_bootstrap_preview_reports_createable_target(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-123"

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["primary_branch"], "main")
        self.assertEqual(payload["base_branch"], "main")
        self.assertEqual(payload["target_branch"], "feature/test")
        self.assertEqual(payload["target_worktree"], str(target_worktree.resolve()))
        self.assertFalse(payload["created"])

    def test_bootstrap_apply_creates_linked_worktree_and_verify_accepts_it(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-apply"

        bootstrap_result = self.run_bootstrap(
            "--branch",
            "feature/test",
            "--worktree",
            str(target_worktree),
            "--apply",
        )
        bootstrap_payload = json.loads(bootstrap_result.stdout)

        self.assertTrue(bootstrap_payload["created"])
        self.assertTrue(target_worktree.exists())
        self.assertEqual(git(self.repo, "branch", "--show-current").stdout.strip(), "main")

        verify_result = self.run_verify(
            "--expected-branch",
            "feature/test",
            "--expected-worktree",
            str(target_worktree),
            "--require-linked-worktree",
            cwd=target_worktree,
        )
        verify_payload = json.loads(verify_result.stdout)

        self.assertTrue(verify_payload["ok"])
        self.assertTrue(verify_payload["linked_worktree"])
        self.assertEqual(verify_payload["branch"], "feature/test")

    def test_bootstrap_preview_rejects_existing_branch(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-existing"
        git(self.repo, "branch", "feature/test", "main")

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertFalse(payload["ok"])
        self.assertIn("target branch already exists locally: feature/test", payload["errors"])

    def test_verify_rejects_primary_checkout_when_linked_worktree_is_required(self) -> None:
        result = self.run_verify("--require-linked-worktree", cwd=self.repo, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["linked_worktree"])


if __name__ == "__main__":
    unittest.main()
