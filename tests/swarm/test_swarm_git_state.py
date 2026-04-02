import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, load_module, write


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = load_module(REPO_ROOT / "catalog/skills/swarm/scripts/git_state.py")


class SwarmGitStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.worktree = Path(self.temp_dir.name) / "swarm-worktree"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Swarm Git State Test")
        git(self.repo, "config", "user.email", "swarm-git-state@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        git(self.repo, "worktree", "add", "-b", "feature/swarm", str(self.worktree), "main")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_detect_primary_branch_falls_back_to_local_main(self) -> None:
        branch, warnings = MODULE.detect_primary_branch(self.repo)

        self.assertEqual(branch, "main")
        self.assertIn("origin/HEAD unavailable; primary branch detected from local refs", warnings)

    def test_linked_worktree_helpers_resolve_primary_checkout(self) -> None:
        self.assertEqual(MODULE.detect_checkout_root(self.worktree), self.worktree.resolve())
        self.assertEqual(MODULE.primary_checkout_root(self.worktree), self.repo.resolve())
        self.assertTrue(MODULE.is_linked_worktree(self.worktree))
        self.assertFalse(MODULE.is_linked_worktree(self.repo))

    def test_resolve_git_path_handles_relative_and_absolute_paths(self) -> None:
        relative = MODULE.resolve_git_path(".git", self.worktree)
        absolute = MODULE.resolve_git_path(str(self.repo), self.worktree)

        self.assertEqual(relative, (self.worktree / ".git").resolve())
        self.assertEqual(absolute, self.repo.resolve())


if __name__ == "__main__":
    unittest.main()
