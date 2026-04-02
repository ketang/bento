import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, load_module, write


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = load_module(REPO_ROOT / "catalog/skills/launch-work/scripts/git_state.py")


class LaunchWorkGitStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.worktree = Path(self.temp_dir.name) / "feature-launch"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Launch Git State Test")
        git(self.repo, "config", "user.email", "launch-git-state@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        git(self.repo, "worktree", "add", "-b", "feature/launch", str(self.worktree), "main")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_parse_worktrees_reports_primary_and_linked_checkouts(self) -> None:
        worktrees = MODULE.parse_worktrees(self.repo)
        paths = {entry["path"]: entry for entry in worktrees}

        self.assertIn(str(self.repo.resolve()), paths)
        self.assertIn(str(self.worktree.resolve()), paths)
        self.assertEqual(paths[str(self.repo.resolve())]["branch"], "main")
        self.assertEqual(paths[str(self.worktree.resolve())]["branch"], "feature/launch")

    def test_detect_primary_branch_and_primary_checkout_root(self) -> None:
        branch, warnings = MODULE.detect_primary_branch(self.repo)

        self.assertEqual(branch, "main")
        self.assertIn("origin/HEAD unavailable; primary branch detected from local refs", warnings)
        self.assertEqual(MODULE.primary_checkout_root(self.worktree), self.repo.resolve())


if __name__ == "__main__":
    unittest.main()
