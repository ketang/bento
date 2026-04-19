import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PREPARE_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-prepare.py"
PREVIEW_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-create-preview.py"
LEASE_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-verify-lease.py"
VERIFY_LANDING_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-verify-landing.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


class LandWorkScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.worktree = Path(self.temp_dir.name) / "feature-worktree"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Land Work Test")
        git(self.repo, "config", "user.email", "land-work@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

        git(self.repo, "worktree", "add", "-b", "feature/test", str(self.worktree), "main")
        (self.worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
        git(self.worktree, "add", "feature.txt")
        git(self.worktree, "commit", "-m", "feature change")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_prepare(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(PREPARE_SCRIPT), *args], cwd, check=check)

    def run_lease(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(LEASE_SCRIPT), *args], cwd, check=check)

    def run_preview(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(PREVIEW_SCRIPT), *args], cwd, check=check)

    def run_verify_landing(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(VERIFY_LANDING_SCRIPT), *args], cwd, check=check)

    def test_prepare_accepts_clean_feature_branch_worktree(self) -> None:
        result = self.run_prepare("--expected-branch", "feature/test", "--require-linked-worktree", cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["branch"], "feature/test")
        self.assertEqual(payload["primary_branch"], "main")
        self.assertTrue(payload["linked_worktree"])
        self.assertFalse(payload["working_tree_dirty"])
        self.assertEqual(payload["preferred_rebase_base"], "main")
        self.assertEqual(payload["ahead_of_primary"], 1)

    def test_prepare_rejects_primary_checkout(self) -> None:
        result = self.run_prepare("--require-linked-worktree", cwd=self.repo, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "current branch is the primary branch; land-work must run from a feature branch",
            payload["errors"],
        )

    def test_prepare_rejects_dirty_worktree(self) -> None:
        (self.worktree / "feature.txt").write_text("dirty\n", encoding="utf-8")

        result = self.run_prepare(cwd=self.worktree, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("working tree is dirty", payload["errors"])

    def test_prepare_rejects_branch_behind_primary_when_required(self) -> None:
        (self.repo / "README.md").write_text("main advanced\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "advance main")

        result = self.run_prepare("--require-up-to-date", cwd=self.worktree, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["require_up_to_date_satisfied"])
        self.assertIn("current branch is behind the primary branch by 1 commit(s)", payload["errors"])

    def test_preview_creates_clean_merge_candidate(self) -> None:
        base_sha = git(self.repo, "rev-parse", "refs/heads/main").stdout.strip()
        feature_sha = git(self.worktree, "rev-parse", "HEAD").stdout.strip()
        preview_dir = Path(self.temp_dir.name) / "preview-clean"
        result = self.run_preview(
            "--base-ref",
            base_sha,
            "--feature-ref",
            feature_sha,
            "--preview-dir",
            str(preview_dir),
            cwd=self.worktree,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["merge_clean"])
        self.assertEqual(payload["base_sha"], base_sha)
        self.assertEqual(payload["feature_sha"], feature_sha)
        self.assertEqual(payload["preview_dir"], str(preview_dir.resolve()))
        self.assertIsNotNone(payload["preview_tree"])
        self.assertEqual((preview_dir / "feature.txt").read_text(encoding="utf-8"), "feature\n")

    def test_preview_rejects_conflicting_merge_candidate(self) -> None:
        (self.repo / "README.md").write_text("main branch\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "main edit")

        (self.worktree / "README.md").write_text("feature branch\n", encoding="utf-8")
        git(self.worktree, "add", "README.md")
        git(self.worktree, "commit", "-m", "feature edit")

        preview_dir = Path(self.temp_dir.name) / "preview-conflict"
        result = self.run_preview("--preview-dir", str(preview_dir), cwd=self.worktree, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["merge_clean"])
        self.assertIn("merge preview has conflicts", payload["errors"])
        self.assertIn("README.md", payload["conflicting_paths"])

    def test_lease_check_matches_expected_sha(self) -> None:
        expected_sha = git(self.repo, "rev-parse", "refs/heads/main").stdout.strip()

        result = self.run_lease("--ref", "refs/heads/main", "--expected-sha", expected_sha, cwd=self.repo)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["lease_matches"])
        self.assertEqual(payload["resolved_sha"], expected_sha)

    def test_lease_check_rejects_sha_mismatch(self) -> None:
        result = self.run_lease("--ref", "refs/heads/main", "--expected-sha", "deadbeef", cwd=self.repo, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("lease mismatch for refs/heads/main", payload["errors"])

    def test_verify_landing_matches_preview_tree(self) -> None:
        preview_dir = Path(self.temp_dir.name) / "preview-landed"
        preview_result = self.run_preview("--preview-dir", str(preview_dir), cwd=self.worktree)
        preview_payload = json.loads(preview_result.stdout)

        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature/test")

        result = self.run_verify_landing(
            "--ref",
            "refs/heads/main",
            "--expected-tree",
            preview_payload["preview_tree"],
            cwd=self.repo,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["tree_matches"])
        self.assertEqual(payload["resolved_tree"], preview_payload["preview_tree"])

    def test_verify_landing_rejects_tree_mismatch(self) -> None:
        result = self.run_verify_landing("--ref", "refs/heads/main", "--expected-tree", "deadbeef", cwd=self.repo, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["tree_matches"])
        self.assertIn("landed tree mismatch for refs/heads/main", payload["errors"])


if __name__ == "__main__":
    unittest.main()
