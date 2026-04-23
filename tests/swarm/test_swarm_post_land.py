import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, write


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-post-land.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


class SwarmPostLandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Swarm Post-Land Test")
        git(self.repo, "config", "user.email", "swarm@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        git(self.repo, "branch", "release-branch")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_rebase_landing_target_onto_primary_dry_run(self) -> None:
        result = run(
            [str(SCRIPT), "--hook", "rebase-landing-target-onto-primary",
             "--landing-target", "release-branch", "--primary", "main"],
            cwd=self.repo,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["hook"], "rebase-landing-target-onto-primary")

    def test_rebase_landing_target_onto_primary_apply(self) -> None:
        # advance main ahead of release-branch
        write(self.repo / "main-only.txt", "hi\n")
        git(self.repo, "add", "main-only.txt")
        git(self.repo, "commit", "-m", "advance main")

        git(self.repo, "checkout", "release-branch")
        result = run(
            [str(SCRIPT), "--hook", "rebase-landing-target-onto-primary",
             "--landing-target", "release-branch", "--primary", "main", "--apply"],
            cwd=self.repo,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["applied"])
        self.assertTrue((self.repo / "main-only.txt").exists())

    def test_unknown_hook_is_rejected(self) -> None:
        result = run(
            [str(SCRIPT), "--hook", "no-such-hook",
             "--landing-target", "release-branch", "--primary", "main"],
            cwd=self.repo,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
