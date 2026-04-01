import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/closure/scripts/closure-scan.py"


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd)


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class ClosureScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Closure Test")
        git(self.repo, "config", "user.email", "closure@example.com")
        self.commit_file("README.md", "root\n", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def commit_file(self, relative_path: str, content: str, message: str) -> str:
        path = self.repo / relative_path
        write_file(path, content)
        git(self.repo, "add", relative_path)
        git(self.repo, "commit", "-m", message)
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def setup_branch_scenarios(self) -> None:
        git(self.repo, "checkout", "-b", "feature-merged")
        self.commit_file("merged.txt", "merged\n", "add merged work")
        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "--no-ff", "feature-merged", "-m", "merge feature-merged")

        git(self.repo, "checkout", "-b", "feature-equivalent")
        equivalent_commit = self.commit_file("equivalent.txt", "equivalent\n", "add equivalent work")
        git(self.repo, "checkout", "main")
        self.commit_file("main-only.txt", "main only\n", "add main divergence")
        git(self.repo, "cherry-pick", equivalent_commit)

        git(self.repo, "checkout", "-b", "feature-open")
        self.commit_file("open.txt", "open\n", "add open work")
        git(self.repo, "checkout", "main")

    def run_scan(self, *args: str) -> dict:
        result = run(["python3", str(SCRIPT), *args], self.repo)
        return json.loads(result.stdout)

    def branch_record(self, scan: dict, branch_name: str) -> dict:
        for branch in scan["local_branches"]:
            if branch["name"] == branch_name:
                return branch
        self.fail(f"missing branch record for {branch_name}")

    def test_scan_classifies_safe_equivalent_and_open_branches(self) -> None:
        self.setup_branch_scenarios()

        scan = self.run_scan()

        self.assertEqual(scan["primary_branch"], "main")
        self.assertIn("feature-merged", scan["summary"]["safe_to_delete_local_branches"])
        self.assertIn("feature-equivalent", scan["summary"]["patch_equivalent_local_branches"])
        self.assertIn("feature-open", scan["summary"]["local_branches_requiring_review"])

        self.assertEqual(self.branch_record(scan, "feature-merged")["classification"], "safe_to_delete")
        self.assertEqual(
            self.branch_record(scan, "feature-equivalent")["classification"],
            "patch_equivalent_review",
        )
        self.assertEqual(self.branch_record(scan, "feature-open")["classification"], "review_required")

    def test_apply_deletes_only_local_merged_branches(self) -> None:
        self.setup_branch_scenarios()

        scan = self.run_scan("--apply", "delete-local-merged-branches")
        branches = git(self.repo, "branch", "--format=%(refname:short)").stdout.splitlines()

        self.assertEqual(scan["apply_mode"], "delete-local-merged-branches")
        self.assertIn(
            {"action": "delete_local_branch", "branch": "feature-merged"},
            scan["applied_actions"],
        )
        self.assertNotIn("feature-merged", branches)
        self.assertIn("feature-equivalent", branches)
        self.assertIn("feature-open", branches)


if __name__ == "__main__":
    unittest.main()
