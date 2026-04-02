import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, load_module, write


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = load_module(REPO_ROOT / "catalog/skills/land-work/scripts/git_state.py")


class LandWorkGitStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.worktree = Path(self.temp_dir.name) / "feature-land"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Land Git State Test")
        git(self.repo, "config", "user.email", "land-git-state@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        git(self.repo, "worktree", "add", "-b", "feature/land", str(self.worktree), "main")
        write(self.worktree / "feature.txt", "feature\n")
        git(self.worktree, "add", "feature.txt")
        git(self.worktree, "commit", "-m", "feature commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ahead_behind_and_branch_resolution_for_feature_branch(self) -> None:
        behind, ahead = MODULE.ahead_behind("main", "feature/land", self.worktree)

        self.assertEqual((behind, ahead), (0, 1))
        self.assertEqual(MODULE.current_branch(self.worktree), "feature/land")
        self.assertEqual(MODULE.rev_parse("refs/heads/main", self.repo), git(self.repo, "rev-parse", "refs/heads/main").stdout.strip())

    def test_working_tree_dirty_and_ref_exists(self) -> None:
        self.assertFalse(MODULE.working_tree_dirty(self.worktree))
        self.assertTrue(MODULE.ref_exists("refs/heads/main", self.repo))
        self.assertFalse(MODULE.ref_exists("refs/heads/missing", self.repo))

        write(self.worktree / "feature.txt", "dirty\n")

        self.assertTrue(MODULE.working_tree_dirty(self.worktree))
        self.assertTrue(MODULE.is_linked_worktree(self.worktree))


if __name__ == "__main__":
    unittest.main()
