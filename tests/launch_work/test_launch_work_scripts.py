import json
import os
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

    def run_bootstrap_env(
        self, *args: str, cwd: Path | None = None, env: dict | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(BOOTSTRAP_SCRIPT), *args],
            cwd=cwd or self.repo,
            capture_output=True,
            text=True,
            check=check,
            env=env,
        )

    def _fake_bin(self, name: str, script: str) -> Path:
        bin_dir = Path(self.temp_dir.name) / "fakebin"
        bin_dir.mkdir(exist_ok=True)
        path = bin_dir / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
        return bin_dir

    def _env_with_path(self, *extra_bin_dirs: Path) -> dict:
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join([*(str(d) for d in extra_bin_dirs), env.get("PATH", "")])
        return env

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

    # -- bento-rdtn.13: bare checkout reports a diagnostic, never a traceback #

    def test_bootstrap_bare_checkout_reports_diagnostic_not_traceback(self) -> None:
        git(self.repo, "config", "core.bare", "true")
        target_worktree = Path(self.temp_dir.name) / "feature-bare"

        result = self.run_bootstrap(
            "--branch", "feature/test", "--worktree", str(target_worktree), check=False
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.strip(), "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "not_a_work_tree")
        self.assertIn("work tree", payload["detail"])
        self.assertIn("core.bare", payload["hint"])
        self.assertTrue(payload["is_bare_repository"])
        self.assertFalse(payload["is_inside_git_dir"])
        self.assertTrue(payload["is_git_repository"])

    def test_verify_bare_checkout_reports_diagnostic_not_traceback(self) -> None:
        git(self.repo, "config", "core.bare", "true")

        result = self.run_verify(cwd=self.repo, check=False)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.strip(), "")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "not_a_work_tree")
        self.assertTrue(payload["is_bare_repository"])

    def test_bootstrap_inside_git_dir_reports_diagnostic(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-inside-git-dir"

        result = self.run_bootstrap(
            "--branch",
            "feature/test",
            "--worktree",
            str(target_worktree),
            cwd=self.repo / ".git",
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "not_a_work_tree")
        self.assertFalse(payload["is_bare_repository"])
        self.assertTrue(payload["is_inside_git_dir"])
        self.assertTrue(payload["is_git_repository"])

    # -- bento-rdtn.7: --claim -------------------------------------------- #

    def test_claim_auto_skipped_on_non_matching_branch_name(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "featureworktree"
        result = self.run_bootstrap(
            "--branch", "featurebranch", "--worktree", str(target_worktree),
            "--apply", "--claim", "auto",
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["created"])
        self.assertEqual(payload["claim"]["status"], "skipped")
        self.assertIsNone(payload["claim"]["tracker"])
        self.assertIsNone(payload["claim"]["id"])
        self.assertTrue(any("does not match" in w for w in payload["warnings"]))

    def test_claim_auto_extracts_leading_prefix_id_token(self) -> None:
        (self.repo / ".beads").mkdir()
        bin_dir = self._fake_bin(
            "bd", '#!/bin/sh\necho "$@" > "$FAKE_BD_LOG"\nexit 0\n'
        )
        log_path = Path(self.temp_dir.name) / "bd.log"
        target_worktree = Path(self.temp_dir.name) / "str-25kcm-feature"
        env = self._env_with_path(bin_dir)
        env["FAKE_BD_LOG"] = str(log_path)
        result = self.run_bootstrap_env(
            "--branch", "str-25kcm-fix-thing", "--worktree", str(target_worktree),
            "--apply", "--claim", "auto", env=env,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["claim"]["status"], "claimed")
        self.assertEqual(payload["claim"]["tracker"], "beads")
        self.assertEqual(payload["claim"]["id"], "str-25kcm")
        self.assertEqual(log_path.read_text().strip(), "update str-25kcm --claim")

    def test_claim_auto_reconstructs_dotted_subissue_id_from_hyphenated_branch(self) -> None:
        # bento's own branch-naming convention renders a dotted sub-issue id
        # ("bento-rdtn.7") with a hyphen instead of a literal dot
        # ("bento-rdtn-7-slug") -- auto must resolve the real sub-issue, not
        # just truncate to the epic id "bento-rdtn".
        (self.repo / ".beads").mkdir()
        bin_dir = self._fake_bin(
            "bd", '#!/bin/sh\necho "$@" > "$FAKE_BD_LOG"\nexit 0\n'
        )
        log_path = Path(self.temp_dir.name) / "bd.log"
        target_worktree = Path(self.temp_dir.name) / "bento-rdtn-7-bootstrap-claim"
        env = self._env_with_path(bin_dir)
        env["FAKE_BD_LOG"] = str(log_path)
        result = self.run_bootstrap_env(
            "--branch", "bento-rdtn-7-bootstrap-claim", "--worktree", str(target_worktree),
            "--apply", "--claim", "auto", env=env,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["claim"]["status"], "claimed")
        self.assertEqual(payload["claim"]["id"], "bento-rdtn.7")
        self.assertEqual(log_path.read_text().strip(), "update bento-rdtn.7 --claim")

    def test_claim_explicit_id_with_beads_tracker(self) -> None:
        (self.repo / ".beads").mkdir()
        bin_dir = self._fake_bin("bd", "#!/bin/sh\nexit 0\n")
        target_worktree = Path(self.temp_dir.name) / "feature-explicit"
        result = self.run_bootstrap_env(
            "--branch", "feature/explicit", "--worktree", str(target_worktree),
            "--apply", "--claim", "myproj-42", env=self._env_with_path(bin_dir),
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["claim"]["status"], "claimed")
        self.assertEqual(payload["claim"]["tracker"], "beads")
        self.assertEqual(payload["claim"]["id"], "myproj-42")

    def test_claim_failed_beads_command_records_warning_with_exact_command(self) -> None:
        (self.repo / ".beads").mkdir()
        bin_dir = self._fake_bin("bd", "#!/bin/sh\necho 'issue not found' >&2\nexit 1\n")
        target_worktree = Path(self.temp_dir.name) / "feature-failed-claim"
        result = self.run_bootstrap_env(
            "--branch", "feature/failed", "--worktree", str(target_worktree),
            "--apply", "--claim", "nope-1", env=self._env_with_path(bin_dir),
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["created"])
        self.assertEqual(payload["claim"]["status"], "failed")
        self.assertTrue(
            any("bd update nope-1 --claim" in w for w in payload["warnings"])
        )

    def test_claim_with_github_tracker_when_no_beads_dir(self) -> None:
        git(self.repo, "remote", "add", "origin", "https://github.com/example/repo.git")
        bin_dir = self._fake_bin(
            "gh", '#!/bin/sh\necho "$@" > "$FAKE_GH_LOG"\nexit 0\n'
        )
        log_path = Path(self.temp_dir.name) / "gh.log"
        env = self._env_with_path(bin_dir)
        env["FAKE_GH_LOG"] = str(log_path)
        target_worktree = Path(self.temp_dir.name) / "feature-github"
        result = self.run_bootstrap_env(
            "--branch", "feature/gh", "--worktree", str(target_worktree),
            "--apply", "--claim", "123", env=env,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["claim"]["status"], "claimed")
        self.assertEqual(payload["claim"]["tracker"], "github")
        self.assertEqual(log_path.read_text().strip(), "issue edit 123 --add-assignee @me")

    def test_claim_skipped_when_no_tracker_detected(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-no-tracker"
        result = self.run_bootstrap(
            "--branch", "feature/none", "--worktree", str(target_worktree),
            "--apply", "--claim", "1",
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["claim"]["status"], "skipped")
        self.assertTrue(any("no tracker detected" in w for w in payload["warnings"]))

    def test_no_claim_flag_omits_claim_key(self) -> None:
        target_worktree = Path(self.temp_dir.name) / "feature-noclaim"
        result = self.run_bootstrap(
            "--branch", "feature/noclaim", "--worktree", str(target_worktree), "--apply",
        )
        payload = json.loads(result.stdout)
        self.assertNotIn("claim", payload)

    def test_claim_never_runs_in_preview_mode(self) -> None:
        # Acceptance: the claim happens after the worktree exists -- so a
        # dry-run preview (no --apply) must never invoke the tracker.
        (self.repo / ".beads").mkdir()
        bin_dir = self._fake_bin("bd", "#!/bin/sh\nexit 1\n")  # would fail loudly if invoked
        target_worktree = Path(self.temp_dir.name) / "feature-preview"
        result = self.run_bootstrap_env(
            "--branch", "feature/preview", "--worktree", str(target_worktree),
            "--claim", "auto", env=self._env_with_path(bin_dir),
        )
        payload = json.loads(result.stdout)
        self.assertFalse(payload["created"])
        self.assertNotIn("claim", payload)

    def test_bootstrap_non_repo_reports_diagnostic(self) -> None:
        non_repo = Path(self.temp_dir.name) / "plain-dir"
        non_repo.mkdir()
        target_worktree = Path(self.temp_dir.name) / "feature-non-repo"

        result = self.run_bootstrap(
            "--branch", "feature/test", "--worktree", str(target_worktree), cwd=non_repo, check=False
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "not_a_work_tree")
        self.assertFalse(payload["is_bare_repository"])
        self.assertFalse(payload["is_inside_git_dir"])
        self.assertFalse(payload["is_git_repository"])


if __name__ == "__main__":
    unittest.main()
