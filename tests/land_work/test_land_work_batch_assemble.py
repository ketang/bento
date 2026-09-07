import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, run


REPO_ROOT = Path(__file__).resolve().parents[2]
ASSEMBLE_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-batch-assemble.py"


class LandWorkBatchAssembleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.integration = Path(self.temp_dir.name) / "integration"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Batch Assemble Test")
        git(self.repo, "config", "user.email", "batch-assemble@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        self.base_sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()

        git(self.repo, "worktree", "add", "--detach", str(self.integration), self.base_sha)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_branch(self, name: str, filename: str, content: str, base: str = "main") -> None:
        git(self.repo, "branch", name, base)
        worktree = Path(self.temp_dir.name) / f"wt-{name}"
        git(self.repo, "worktree", "add", str(worktree), name)
        (worktree / filename).write_text(content, encoding="utf-8")
        git(worktree, "add", filename)
        git(worktree, "commit", "-m", f"{name}: add {filename}")
        git(self.repo, "worktree", "remove", "--force", str(worktree))

    def run_assemble(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(ASSEMBLE_SCRIPT), *args], self.repo, check=check)

    def test_assembles_all_non_conflicting_branches_in_order(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")
        self._make_branch("branch-b", "b.txt", "b\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "branch-b",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual([entry["branch"] for entry in payload["assembled"]], ["branch-a", "branch-b"])
        self.assertEqual(payload["evicted"], [])
        self.assertEqual((self.integration / "a.txt").read_text(encoding="utf-8"), "a\n")
        self.assertEqual((self.integration / "b.txt").read_text(encoding="utf-8"), "b\n")
        self.assertNotEqual(payload["tip_sha"], self.base_sha)

    def test_conflicting_branch_is_evicted_and_others_still_land(self) -> None:
        self._make_branch("branch-a", "shared.txt", "from a\n")
        self._make_branch("branch-b", "shared.txt", "from b\n")
        self._make_branch("branch-c", "c.txt", "c\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "branch-b",
            "--branch", "branch-c",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual([entry["branch"] for entry in payload["assembled"]], ["branch-a", "branch-c"])
        self.assertEqual(len(payload["evicted"]), 1)
        self.assertEqual(payload["evicted"][0]["branch"], "branch-b")
        self.assertIn("shared.txt", payload["evicted"][0]["conflicting_paths"])
        self.assertEqual((self.integration / "shared.txt").read_text(encoding="utf-8"), "from a\n")
        self.assertEqual((self.integration / "c.txt").read_text(encoding="utf-8"), "c\n")

    def test_worktree_left_clean_after_eviction(self) -> None:
        self._make_branch("branch-a", "shared.txt", "from a\n")
        self._make_branch("branch-b", "shared.txt", "from b\n")

        self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "branch-b",
        )

        status = git(self.integration, "status", "--porcelain=v1", "--untracked-files=all").stdout
        self.assertEqual(status.strip(), "")
        # A worktree's own .git is a file pointing at the admin dir; resolve it.
        git_dir = Path(git(self.integration, "rev-parse", "--git-dir").stdout.strip())
        if not git_dir.is_absolute():
            git_dir = self.integration / git_dir
        self.assertFalse((git_dir / "MERGE_HEAD").exists())

    def test_no_branches_leaves_tip_at_base(self) -> None:
        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["assembled"], [])
        self.assertEqual(payload["evicted"], [])
        self.assertEqual(payload["tip_sha"], self.base_sha)

    def test_nonexistent_branch_is_evicted_with_reason(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "does-not-exist",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual([entry["branch"] for entry in payload["assembled"]], ["branch-a"])
        self.assertEqual(len(payload["evicted"]), 1)
        self.assertEqual(payload["evicted"][0]["branch"], "does-not-exist")
        self.assertIn("does not exist", payload["evicted"][0]["reason"])

    def test_resets_worktree_to_base_ref_before_assembling(self) -> None:
        # A worktree left mid-merge or advanced from a prior batch attempt
        # must not leak into the next assemble call.
        self._make_branch("stale", "stale.txt", "stale\n")
        git(self.integration, "merge", "--no-ff", "stale")
        self._make_branch("branch-a", "a.txt", "a\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse((self.integration / "stale.txt").exists())
        self.assertEqual((self.integration / "a.txt").read_text(encoding="utf-8"), "a\n")

    def test_refuses_to_reset_over_foreign_untracked_files(self) -> None:
        # Regression: SKILL.md documents that the worktree is validated
        # "exactly as land-work-create-preview.py does for a single
        # landing" — foreign, non-ignored untracked content means a person
        # or another tool touched the shared worktree and must not be
        # silently reset over.
        self._make_branch("branch-a", "a.txt", "a\n")
        (self.integration / "real-work.txt").write_text("not reproducible\n", encoding="utf-8")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("untracked files", payload["errors"][0])
        self.assertEqual(
            (self.integration / "real-work.txt").read_text(encoding="utf-8"), "not reproducible\n"
        )

    def test_rejects_worktree_not_registered_to_this_repo(self) -> None:
        unrelated = Path(self.temp_dir.name) / "unrelated"
        unrelated.mkdir()
        git(unrelated, "init", "-b", "main")

        result = self.run_assemble(
            "--worktree", str(unrelated),
            "--base-ref", self.base_sha,
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("not a registered git worktree", payload["errors"][0])

    def test_merge_commit_message_references_branch(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")

        self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
        )

        subject = git(self.integration, "log", "-1", "--format=%s").stdout.strip()
        self.assertIn("branch-a", subject)


if __name__ == "__main__":
    unittest.main()
