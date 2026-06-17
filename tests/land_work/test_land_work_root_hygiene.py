import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, run


REPO_ROOT = Path(__file__).resolve().parents[2]
HYGIENE_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-root-hygiene.py"


class LandWorkRootHygieneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.worktree = Path(self.temp_dir.name) / "feature-worktree"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Land Work Test")
        git(self.repo, "config", "user.email", "land-work@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("ignored.txt\nbuild/\n", encoding="utf-8")
        git(self.repo, "add", "README.md", ".gitignore")
        git(self.repo, "commit", "-m", "initial commit")

        git(self.repo, "worktree", "add", "-b", "feature/test", str(self.worktree), "main")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_hygiene(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(HYGIENE_SCRIPT), *args], cwd, check=check)

    def test_clean_root_reports_no_untracked_paths(self) -> None:
        result = self.run_hygiene(cwd=self.repo)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["clean"])
        self.assertEqual(payload["untracked_paths"], [])
        self.assertEqual(payload["primary_checkout_root"], str(self.repo.resolve()))

    def test_uncovered_untracked_file_is_surfaced(self) -> None:
        (self.repo / "junk.txt").write_text("junk\n", encoding="utf-8")

        result = self.run_hygiene(cwd=self.repo)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["clean"])
        self.assertIn("junk.txt", payload["untracked_paths"])

    def test_gitignored_file_adds_no_noise(self) -> None:
        (self.repo / "ignored.txt").write_text("noise\n", encoding="utf-8")
        (self.repo / "build").mkdir()
        (self.repo / "build" / "artifact.o").write_text("obj\n", encoding="utf-8")

        result = self.run_hygiene(cwd=self.repo)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["clean"])
        self.assertEqual(payload["untracked_paths"], [])

    def test_untracked_directory_is_expanded_to_files(self) -> None:
        (self.repo / "scratch").mkdir()
        (self.repo / "scratch" / "a.txt").write_text("a\n", encoding="utf-8")
        (self.repo / "scratch" / "b.txt").write_text("b\n", encoding="utf-8")

        result = self.run_hygiene(cwd=self.repo)
        payload = json.loads(result.stdout)

        self.assertFalse(payload["clean"])
        self.assertIn("scratch/a.txt", payload["untracked_paths"])
        self.assertIn("scratch/b.txt", payload["untracked_paths"])

    def test_audits_primary_root_from_linked_worktree(self) -> None:
        # junk in primary root must surface even when script runs from the feature worktree
        (self.repo / "primary-junk.txt").write_text("junk\n", encoding="utf-8")

        result = self.run_hygiene(cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["primary_checkout_root"], str(self.repo.resolve()))
        self.assertFalse(payload["clean"])
        self.assertIn("primary-junk.txt", payload["untracked_paths"])

    def test_explicit_root_argument_is_honored(self) -> None:
        (self.repo / "junk.txt").write_text("junk\n", encoding="utf-8")

        result = self.run_hygiene("--root", str(self.repo), cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["primary_checkout_root"], str(self.repo.resolve()))
        self.assertIn("junk.txt", payload["untracked_paths"])


if __name__ == "__main__":
    unittest.main()
