import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, run


REPO_ROOT = Path(__file__).resolve().parents[2]
PREPARE_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-prepare.py"
PREVIEW_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-create-preview.py"
LEASE_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-verify-lease.py"
VERIFY_LANDING_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-verify-landing.py"


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

    def test_preview_cleanup_removes_registered_worktree(self) -> None:
        preview_dir = Path(self.temp_dir.name) / "preview-to-clean"
        self.run_preview("--preview-dir", str(preview_dir), cwd=self.worktree)
        registered_before = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertIn(str(preview_dir.resolve()), registered_before)
        self.assertTrue(preview_dir.exists())

        result = self.run_preview("--cleanup", "--preview-dir", str(preview_dir), cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["cleaned_up"])
        registered_after = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertNotIn(str(preview_dir.resolve()), registered_after)
        self.assertFalse(preview_dir.exists())

    def test_preview_cleanup_is_idempotent_on_missing_dir(self) -> None:
        missing = Path(self.temp_dir.name) / "no-such-preview"
        result = self.run_preview("--cleanup", "--preview-dir", str(missing), cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["cleaned_up"])

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

    def test_preview_cleans_up_worktree_on_conflict(self) -> None:
        (self.repo / "README.md").write_text("main branch\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "main edit")

        (self.worktree / "README.md").write_text("feature branch\n", encoding="utf-8")
        git(self.worktree, "add", "README.md")
        git(self.worktree, "commit", "-m", "feature edit")

        preview_dir = Path(self.temp_dir.name) / "preview-conflict-cleanup"
        result = self.run_preview("--preview-dir", str(preview_dir), cwd=self.worktree, check=False)
        payload = json.loads(result.stdout)

        # A failed preview must not leave its scratch worktree behind: neither
        # registered with git nor on disk. Otherwise /tmp/land-work-preview-*
        # dirs accumulate after every conflicting landing attempt (bento-gd2).
        self.assertFalse(payload["merge_clean"])
        self.assertTrue(payload["preview_cleaned_up"])
        registered = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertNotIn(str(preview_dir.resolve()), registered)
        self.assertFalse(preview_dir.exists())

    def test_preview_refuses_when_leftover_preview_worktrees_exist(self) -> None:
        # A leaked scratch preview from an earlier landing attempt (default
        # naming: land-work-preview-*) must block creating another one.
        leftover_result = self.run_preview(cwd=self.worktree)
        leftover_payload = json.loads(leftover_result.stdout)
        leftover_dir = Path(leftover_payload["preview_dir"])
        self.assertTrue(leftover_dir.name.startswith("land-work-preview-"))

        result = self.run_preview(cwd=self.worktree, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn(str(leftover_dir), payload["leftover_previews"])
        joined_errors = " ".join(payload["errors"])
        self.assertIn(str(leftover_dir), joined_errors)
        self.assertIn("--cleanup", joined_errors)

        # Must not have created a second preview worktree.
        self.assertNotIn("preview_dir", payload)

        self.run_preview("--cleanup", "--preview-dir", str(leftover_dir), cwd=self.worktree)

    def test_preview_allow_existing_bypasses_leftover_refusal(self) -> None:
        leftover_result = self.run_preview(cwd=self.worktree)
        leftover_payload = json.loads(leftover_result.stdout)
        leftover_dir = Path(leftover_payload["preview_dir"])

        result = self.run_preview("--allow-existing", cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["merge_clean"])

        self.run_preview("--cleanup", "--preview-dir", str(leftover_dir), cwd=self.worktree)
        self.run_preview("--cleanup", "--preview-dir", payload["preview_dir"], cwd=self.worktree)

    def test_preview_explicit_dir_not_flagged_as_leftover(self) -> None:
        # Custom-named preview dirs (e.g. from other test fixtures or a
        # caller-supplied --preview-dir) are not land-work-preview-* and must
        # never trip the leftover check on themselves.
        preview_dir = Path(self.temp_dir.name) / "custom-preview-name"
        result = self.run_preview("--preview-dir", str(preview_dir), cwd=self.worktree)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])

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

    def test_verify_landing_fails_when_preview_worktree_still_registered(self) -> None:
        preview_dir = Path(self.temp_dir.name) / "preview-not-cleaned"
        self.run_preview("--preview-dir", str(preview_dir), cwd=self.worktree)
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature/test")

        result = self.run_verify_landing(
            "--ref", "refs/heads/main", "--preview-dir", str(preview_dir), cwd=self.repo, check=False
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["preview_dir_registered"])
        self.assertIn(str(preview_dir.resolve()), " ".join(payload["errors"]))

        self.run_preview("--cleanup", "--preview-dir", str(preview_dir), cwd=self.worktree)

    def test_verify_landing_passes_when_preview_worktree_cleaned_up(self) -> None:
        preview_dir = Path(self.temp_dir.name) / "preview-cleaned"
        preview_result = self.run_preview("--preview-dir", str(preview_dir), cwd=self.worktree)
        preview_payload = json.loads(preview_result.stdout)
        git(self.repo, "merge", "--no-ff", "feature/test", "-m", "merge feature/test")
        self.run_preview("--cleanup", "--preview-dir", str(preview_dir), cwd=self.worktree)

        result = self.run_verify_landing(
            "--ref",
            "refs/heads/main",
            "--expected-tree",
            preview_payload["preview_tree"],
            "--preview-dir",
            str(preview_dir),
            cwd=self.repo,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["preview_dir_registered"])


class IntegrationWorktreePreviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.worktree = Path(self.temp_dir.name) / "feature-worktree"
        self.integration_worktree = Path(self.temp_dir.name) / "integration"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Land Work Test")
        git(self.repo, "config", "user.email", "land-work@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("target/\n", encoding="utf-8")
        (self.repo / "swarm-config.json").write_text(
            json.dumps({"landing": {"integration_worktree": str(self.integration_worktree)}}),
            encoding="utf-8",
        )
        git(self.repo, "add", "README.md", ".gitignore", "swarm-config.json")
        git(self.repo, "commit", "-m", "initial commit")

        git(self.repo, "worktree", "add", "-b", "feature/test", str(self.worktree), "main")
        (self.worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
        git(self.worktree, "add", "feature.txt")
        git(self.worktree, "commit", "-m", "feature change")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_preview(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(PREVIEW_SCRIPT), *args], cwd, check=check)

    def test_preview_materializes_into_configured_integration_worktree(self) -> None:
        result = self.run_preview(cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["merge_clean"])
        self.assertEqual(payload["preview_dir"], str(self.integration_worktree.resolve()))
        self.assertTrue(payload["persistent_worktree"])
        self.assertFalse(payload["reused_worktree"])
        self.assertEqual((self.integration_worktree / "feature.txt").read_text(encoding="utf-8"), "feature\n")
        registered = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertIn(str(self.integration_worktree.resolve()), registered)

    def test_second_landing_reuses_integration_worktree_and_keeps_build_cache(self) -> None:
        first = self.run_preview(cwd=self.worktree)
        json.loads(first.stdout)
        cache_marker = self.integration_worktree / "target" / "cache-marker"
        cache_marker.parent.mkdir(parents=True, exist_ok=True)
        cache_marker.write_text("warm\n", encoding="utf-8")

        (self.worktree / "feature2.txt").write_text("feature 2\n", encoding="utf-8")
        git(self.worktree, "add", "feature2.txt")
        git(self.worktree, "commit", "-m", "second feature change")

        second = self.run_preview(cwd=self.worktree)
        payload = json.loads(second.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["persistent_worktree"])
        self.assertTrue(payload["reused_worktree"])
        self.assertEqual((self.integration_worktree / "feature2.txt").read_text(encoding="utf-8"), "feature 2\n")
        self.assertEqual(cache_marker.read_text(encoding="utf-8"), "warm\n")
        registered = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertEqual(registered.count(str(self.integration_worktree.resolve())), 1)

    def test_corrupted_registered_integration_worktree_falls_back_instead_of_crashing(self) -> None:
        # Regression: a registered-but-corrupted worktree (its own .git
        # pointer file removed, e.g. by a partial manual cleanup) must
        # degrade to a scratch preview, not crash main() with an unhandled
        # CalledProcessError from `git status` failing inside it.
        self.run_preview(cwd=self.worktree)
        (self.integration_worktree / ".git").unlink()

        result = self.run_preview(cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["persistent_worktree"])
        self.assertNotEqual(payload["preview_dir"], str(self.integration_worktree.resolve()))
        self.assertTrue(
            any(
                "integration_worktree" in warning and "git status" in warning
                for warning in payload["warnings"]
            )
        )

    def test_dirty_integration_worktree_falls_back_to_scratch_dir(self) -> None:
        first = self.run_preview(cwd=self.worktree)
        json.loads(first.stdout)
        (self.integration_worktree / "uncommitted.txt").write_text("oops\n", encoding="utf-8")

        result = self.run_preview(cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["persistent_worktree"])
        self.assertNotEqual(payload["preview_dir"], str(self.integration_worktree.resolve()))
        self.assertTrue(
            any(
                "integration_worktree" in warning and "uncommitted.txt" in warning
                for warning in payload["warnings"]
            )
        )
        self.assertEqual((self.integration_worktree / "uncommitted.txt").read_text(encoding="utf-8"), "oops\n")

    def test_cleanup_refuses_to_delete_when_config_resolution_fails(self) -> None:
        # Regression: resolve_integration_worktree()'s fail-safe default
        # ("no configured worktree") is correct for preview creation, where
        # the caller falls back to scratch. It must NOT be reused as-is for
        # --cleanup: a transient discovery failure must not be read as "this
        # isn't the persistent worktree, safe to force-remove" — that
        # reintroduces the "persistent worktree deleted" bug via a new
        # trigger. Force a resolution failure via an invalid codex teammate
        # config, which makes swarm-discover.py exit 2.
        self.run_preview(cwd=self.worktree)
        codex_config = self.worktree / ".agent-plugins" / "bento" / "bento" / "swarm" / "config.json"
        codex_config.parent.mkdir(parents=True, exist_ok=True)
        codex_config.write_text("{", encoding="utf-8")  # malformed JSON

        result = self.run_preview(
            "--cleanup", "--preview-dir", str(self.integration_worktree), "--runtime", "codex",
            cwd=self.worktree, check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["cleaned_up"])
        self.assertTrue(self.integration_worktree.exists())
        registered = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertIn(str(self.integration_worktree.resolve()), registered)

    def test_explicit_preview_dir_overrides_configured_integration_worktree(self) -> None:
        explicit_dir = Path(self.temp_dir.name) / "explicit-preview"
        result = self.run_preview("--preview-dir", str(explicit_dir), cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["preview_dir"], str(explicit_dir.resolve()))
        self.assertFalse(payload["persistent_worktree"])
        self.assertFalse(self.integration_worktree.exists())

    def test_cleanup_refuses_to_remove_persistent_integration_worktree(self) -> None:
        self.run_preview(cwd=self.worktree)

        result = self.run_preview("--cleanup", "--preview-dir", str(self.integration_worktree), cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["cleaned_up"])
        self.assertTrue(self.integration_worktree.exists())
        registered = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertIn(str(self.integration_worktree.resolve()), registered)

    def test_conflict_against_integration_worktree_aborts_merge_and_preserves_worktree(self) -> None:
        self.run_preview(cwd=self.worktree)

        (self.repo / "README.md").write_text("main branch\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "main edit")

        (self.worktree / "README.md").write_text("feature branch\n", encoding="utf-8")
        git(self.worktree, "add", "README.md")
        git(self.worktree, "commit", "-m", "feature edit")

        result = self.run_preview(cwd=self.worktree, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["merge_clean"])
        self.assertTrue(payload["persistent_worktree"])
        self.assertFalse(payload["preview_cleaned_up"])
        registered = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertIn(str(self.integration_worktree.resolve()), registered)
        self.assertFalse(working_tree_dirty_for_test(self.integration_worktree))

    def test_first_use_conflict_preserves_freshly_created_integration_worktree(self) -> None:
        # Regression: the very first preview against a not-yet-existing
        # integration worktree must not be deleted on conflict just because
        # this run is the one that created it (worktree_added=True). Deleting
        # it here defeats the whole feature on its very first failure.
        (self.repo / "README.md").write_text("main branch\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "main edit")

        (self.worktree / "README.md").write_text("feature branch\n", encoding="utf-8")
        git(self.worktree, "add", "README.md")
        git(self.worktree, "commit", "-m", "feature edit")

        result = self.run_preview(cwd=self.worktree, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["merge_clean"])
        self.assertTrue(payload["persistent_worktree"])
        self.assertFalse(payload["preview_cleaned_up"])
        self.assertTrue(self.integration_worktree.exists())
        registered = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertIn(str(self.integration_worktree.resolve()), registered)
        self.assertFalse(working_tree_dirty_for_test(self.integration_worktree))

    def test_no_config_keeps_scratch_tmp_behavior_unchanged(self) -> None:
        git(self.worktree, "rm", "swarm-config.json")
        git(self.worktree, "commit", "-m", "remove swarm config")

        result = self.run_preview(cwd=self.worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["persistent_worktree"])
        self.assertTrue(payload["preview_dir"].startswith("/tmp/land-work-preview-"))


def working_tree_dirty_for_test(path: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
