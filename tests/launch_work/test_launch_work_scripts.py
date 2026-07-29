import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, run


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCRIPT = REPO_ROOT / "catalog/skills/launch-work/scripts/launch-work-bootstrap.py"
VERIFY_SCRIPT = REPO_ROOT / "catalog/skills/launch-work/scripts/launch-work-verify.py"


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

    def test_bootstrap_reports_untracked_debt_in_primary_checkout(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-junk"
        (self.repo / "scratch.log").write_text("junk\n", encoding="utf-8")
        (self.repo / "notes").mkdir()
        (self.repo / "notes" / "todo.txt").write_text("junk\n", encoding="utf-8")

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertIn("scratch.log", payload["untracked_advisories"])
        self.assertIn("notes/", payload["untracked_advisories"])
        self.assertTrue(
            any("untracked path(s) not covered by .gitignore" in warning for warning in payload["warnings"])
        )

    def test_bootstrap_ignores_gitignored_paths_in_untracked_advisories(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-ignored"
        (self.repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-m", "add gitignore")
        (self.repo / "scratch.log").write_text("junk\n", encoding="utf-8")

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertEqual(payload["untracked_advisories"], [])

    def test_bootstrap_warns_when_go_binary_is_not_ignored(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-go"
        (self.repo / "go.mod").write_text("module example.com/acme/widgetd\n\ngo 1.22\n", encoding="utf-8")
        git(self.repo, "add", "go.mod")
        git(self.repo, "commit", "-m", "add go module")

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertIn(
            "widgetd (Go build output) is not covered by .gitignore",
            payload["ignore_coverage_advisories"],
        )

    def test_bootstrap_strips_major_version_suffix_from_go_module_path(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-go-v2"
        (self.repo / "go.mod").write_text("module example.com/acme/widgetd/v2\n\ngo 1.22\n", encoding="utf-8")
        git(self.repo, "add", "go.mod")
        git(self.repo, "commit", "-m", "add go module")

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertIn(
            "widgetd (Go build output) is not covered by .gitignore",
            payload["ignore_coverage_advisories"],
        )
        self.assertNotIn(
            "v2 (Go build output) is not covered by .gitignore",
            payload["ignore_coverage_advisories"],
        )

    def test_bootstrap_uses_cmd_dirs_instead_of_module_tail_for_cmd_layout(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-go-cmd"
        (self.repo / "go.mod").write_text("module example.com/acme/widgetd\n\ngo 1.22\n", encoding="utf-8")
        for binary in ("widgetctl", "widgetsrv"):
            cmd_pkg = self.repo / "cmd" / binary
            cmd_pkg.mkdir(parents=True)
            (cmd_pkg / "main.go").write_text("package main\n", encoding="utf-8")
        git(self.repo, "add", "go.mod", "cmd")
        git(self.repo, "commit", "-m", "add go module")

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertEqual(
            payload["ignore_coverage_advisories"],
            [
                "widgetctl (Go build output) is not covered by .gitignore",
                "widgetsrv (Go build output) is not covered by .gitignore",
            ],
        )

    def test_bootstrap_is_quiet_when_go_binary_is_ignored(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-go-clean"
        (self.repo / "go.mod").write_text("module example.com/acme/widgetd\n\ngo 1.22\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("/widgetd\n", encoding="utf-8")
        git(self.repo, "add", "go.mod", ".gitignore")
        git(self.repo, "commit", "-m", "add go module")

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertEqual(payload["ignore_coverage_advisories"], [])

    def test_bootstrap_does_not_flag_a_tracked_dist_directory(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-node"
        (self.repo / "package.json").write_text('{"name": "acme"}\n', encoding="utf-8")
        dist = self.repo / "dist"
        dist.mkdir()
        (dist / "vendored.js").write_text("// checked in\n", encoding="utf-8")
        git(self.repo, "add", "package.json", "dist/vendored.js")
        git(self.repo, "commit", "-m", "add package")

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertEqual(payload["ignore_coverage_advisories"], [])

    def test_bootstrap_clean_repo_reports_no_hygiene_advisories(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-clean"

        result = self.run_bootstrap("--branch", "feature/test", "--worktree", str(target_worktree))
        payload = json.loads(result.stdout)

        self.assertEqual(payload["untracked_advisories"], [])
        self.assertEqual(payload["ignore_coverage_advisories"], [])
        self.assertEqual(
            [
                warning
                for warning in payload["warnings"]
                if "untracked" in warning or "gitignore coverage" in warning
            ],
            [],
        )

    def test_verify_rejects_primary_checkout_when_linked_worktree_is_required(self) -> None:
        result = self.run_verify("--require-linked-worktree", cwd=self.repo, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["linked_worktree"])


if __name__ == "__main__":
    unittest.main()
