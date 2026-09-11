import json
import os
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tests.script_test_utils import git, run


REPO_ROOT = Path(__file__).resolve().parents[2]
LAND_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land.py"
CREATE_PREVIEW_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-create-preview.py"

PASS_VERIFIER = (
    '#!/usr/bin/env bash\n'
    'echo \'{"schema_version":1,"status":"passed",'
    '"selected_checks":[{"name":"make test-quick","status":"passed","executed":true}]}\'\n'
)
FAILED_VERIFIER = (
    '#!/usr/bin/env bash\n'
    'echo \'{"schema_version":1,"status":"failed",'
    '"selected_checks":[{"name":"make test-quick","status":"failed"}]}\'\n'
)


class LandDriverTestBase(unittest.TestCase):
    """A real bare 'origin' remote plus a primary checkout and a feature
    linked worktree, matching land-work's real compare-and-set flow (the
    driver fetches/pushes against an actual remote, not just local refs)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.remote = base / "remote.git"
        self.repo = base / "repo"
        self.worktree = base / "feature-worktree"
        self.verifier_path = base / "verify.sh"

        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(self.remote)],
            check=True, capture_output=True, text=True,
        )
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Land Driver Test")
        git(self.repo, "config", "user.email", "land-driver@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-u", "origin", "main")

        self.install_verifier(PASS_VERIFIER)
        # Committed and pushed before the feature worktree branches off, so
        # the feature branch starts from a main that already includes it --
        # otherwise the feature branch would be behind primary by this
        # commit and --require-up-to-date would (correctly) refuse to land.
        self.write_manifest()

        git(self.repo, "worktree", "add", "-b", "feature/test", str(self.worktree), "main")
        (self.worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
        git(self.worktree, "add", "feature.txt")
        git(self.worktree, "commit", "-m", "feature change")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def install_verifier(self, content: str) -> None:
        self.verifier_path.write_text(content, encoding="utf-8")
        self.verifier_path.chmod(0o755)

    def write_manifest(self) -> None:
        # Committed (not left untracked): a real repo checks this in, and an
        # untracked manifest would make land-work-prepare.py's primary_dirty
        # check correctly refuse to land.
        manifest = {
            "schema_version": 1,
            "command": [str(self.verifier_path)],
            "verified_noop": [],
        }
        path = self.repo / ".agent-plugins/bento/bento/land-work/verifier.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        git(self.repo, "add", str(path.relative_to(self.repo)))
        git(self.repo, "commit", "-m", "add verifier manifest")
        git(self.repo, "push", "origin", "main")

    def run_driver(self, *args: str, env: dict | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
        run_env = dict(os.environ)
        if env:
            run_env.update(env)
        return subprocess.run(
            [str(LAND_SCRIPT), *args], cwd=self.worktree, capture_output=True, text=True,
            env=run_env, check=check,
        )

    def registered_preview_worktrees(self) -> list[str]:
        listing = git(self.repo, "worktree", "list", "--porcelain").stdout
        return [
            line[len("worktree "):]
            for line in listing.splitlines()
            if line.startswith("worktree ") and "land-work-preview-" in line
        ]


class HappyPathTest(LandDriverTestBase):
    def test_full_sequence_lands_and_cleans_up(self) -> None:
        result = self.run_driver()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["failed_step"])
        step_names = [s["step"] for s in payload["steps"]]
        self.assertEqual(
            step_names,
            ["prepare", "fetch", "create_preview", "verify", "lease_check", "merge_push", "cleanup", "verify_landing"],
        )
        self.assertTrue(all(s["status"] == "passed" for s in payload["steps"]))
        # The verify step's executed:true check must report "not cached".
        verify_step = next(s for s in payload["steps"] if s["step"] == "verify")
        self.assertFalse(verify_step["cached"])

        # The primary checkout actually landed the feature content.
        self.assertEqual(
            (self.repo / "feature.txt").read_text(encoding="utf-8"), "feature\n",
        )
        # Pushed to the real remote, not just the local primary ref.
        remote_main = subprocess.run(
            ["git", "rev-parse", "refs/heads/main"], cwd=self.remote, capture_output=True, text=True, check=True,
        ).stdout.strip()
        primary_main = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(remote_main, primary_main)

        self.assertEqual(self.registered_preview_worktrees(), [])

    def test_no_remote_tracking_ref_still_lands(self) -> None:
        # primary_local_vs_remote is null when there's nothing to compare
        # against yet (e.g. a repo whose remote was just added) -- the
        # normal route must still be used, not treated as an error.
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/main")
        result = self.run_driver()
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])


class PushFromPreviewRouteTest(LandDriverTestBase):
    def test_ahead_primary_uses_push_from_preview_route(self) -> None:
        # Simulate the primary's local main gaining a commit the leased
        # remote doesn't have yet (bento-rdtn.5's "ahead" diagnostic),
        # deliberately never pushed. Rebase the feature branch onto it so the
        # feature branch itself is not behind the local primary --
        # --require-up-to-date is a separate, orthogonal check from
        # primary_local_vs_remote.
        (self.repo / "extra.txt").write_text("more\n", encoding="utf-8")
        git(self.repo, "add", "extra.txt")
        git(self.repo, "commit", "-m", "local-only commit on primary")
        git(self.worktree, "rebase", "main")

        result = self.run_driver()
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])

        # Both the extra local-only commit's content and the feature content
        # must be present -- the push-from-preview route must not drop it.
        self.assertTrue((self.repo / "extra.txt").exists())
        self.assertTrue((self.repo / "feature.txt").exists())
        remote_main = subprocess.run(
            ["git", "rev-parse", "refs/heads/main"], cwd=self.remote, capture_output=True, text=True, check=True,
        ).stdout.strip()
        primary_main = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(remote_main, primary_main)
        self.assertEqual(self.registered_preview_worktrees(), [])

    def test_sync_failure_after_successful_push_is_a_warning_not_a_failure(self) -> None:
        # Code review (bento-rdtn.14): if the primary checkout gains an
        # incompatible local commit in the window between push-from-preview's
        # push and its best-effort primary sync (a race, not something
        # --require-up-to-date at prepare time could have caught), the
        # landing itself already succeeded on origin -- ff-only failing to
        # sync the primary's local branch afterward must be a warning, not a
        # reported failure, and must never force-reset the primary.
        (self.repo / "extra.txt").write_text("more\n", encoding="utf-8")
        git(self.repo, "add", "extra.txt")
        git(self.repo, "commit", "-m", "local-only commit on primary")
        git(self.worktree, "rebase", "main")
        # This is now an "ahead" primary compatible with feature (as in the
        # test above) -- inject a SECOND, incompatible local commit during
        # the driver's own primary-sync window so ff-only cannot succeed.
        env = {"BENTO_LAND_TEST_DELAY_PRIMARY_SYNC": "1.0"}

        def _inject_incompatible_commit() -> None:
            time.sleep(0.4)
            (self.repo / "race.txt").write_text("race\n", encoding="utf-8")
            git(self.repo, "add", "race.txt")
            git(self.repo, "commit", "-m", "incompatible race commit on primary")

        threading.Thread(target=_inject_incompatible_commit).start()
        result = self.run_driver(env=env)
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload.get("warning"))
        self.assertIn("fast-forward", payload["warning"])

        # The landing itself succeeded on origin regardless of the local
        # primary sync outcome.
        remote_main = subprocess.run(
            ["git", "rev-parse", "refs/heads/main"], cwd=self.remote, capture_output=True, text=True, check=True,
        ).stdout.strip()
        remote_tree = subprocess.run(
            ["git", "log", "-1", "--format=%T", remote_main], cwd=self.remote, capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertIn("feature.txt", subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", remote_tree], cwd=self.remote, capture_output=True, text=True, check=True,
        ).stdout)

        # The primary's local race commit was never force-reset or discarded.
        self.assertIn("race commit", git(self.repo, "log", "-1", "--format=%s").stdout)
        self.assertEqual(self.registered_preview_worktrees(), [])


class BehindPrimaryTest(LandDriverTestBase):
    def test_behind_primary_syncs_to_leased_base_before_merging(self) -> None:
        # Code review (bento-rdtn.14): the preview is built from the leased
        # origin ref, not from whatever the primary checkout's local branch
        # currently points at. Simulate the primary's local main lagging
        # origin (another session pushed directly) -- the normal route must
        # fast-forward the primary to the leased base before merging, or the
        # resulting tree diverges from the verified preview.
        other_clone = Path(self.temp_dir.name) / "other-clone"
        subprocess.run(
            ["git", "clone", str(self.remote), str(other_clone)], check=True, capture_output=True, text=True,
        )
        git(other_clone, "config", "user.name", "Other Session")
        git(other_clone, "config", "user.email", "other@example.com")
        (other_clone / "upstream-only.txt").write_text("upstream\n", encoding="utf-8")
        git(other_clone, "add", "upstream-only.txt")
        git(other_clone, "commit", "-m", "pushed directly by another session")
        git(other_clone, "push", "origin", "main")
        # The primary checkout's local main deliberately does NOT fetch this
        # -- it is now "behind" origin/main.

        # Rebase the feature branch onto the new origin/main so the feature
        # branch itself is not behind (an orthogonal --require-up-to-date
        # check); the primary checkout's local main is still stale.
        git(self.worktree, "fetch", "origin")
        git(self.worktree, "rebase", "origin/main")

        result = self.run_driver()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        # Both the other session's upstream commit and the feature content
        # must be present -- a stale-base merge would have silently dropped
        # the upstream-only commit's ancestry.
        self.assertTrue((self.repo / "upstream-only.txt").exists())
        self.assertTrue((self.repo / "feature.txt").exists())
        remote_main = subprocess.run(
            ["git", "rev-parse", "refs/heads/main"], cwd=self.remote, capture_output=True, text=True, check=True,
        ).stdout.strip()
        primary_main = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(remote_main, primary_main)
        self.assertEqual(self.registered_preview_worktrees(), [])


class IntegrationWorktreeLandingTest(unittest.TestCase):
    """Code review (bento-rdtn.14): land.py must not pass --preview-dir to
    verify-landing for a persistent landing.integration_worktree, since
    create-preview.py's --cleanup is a documented no-op against it (it's
    meant to persist across landings) -- passing --preview-dir there would
    always fail verify-landing because the worktree is still registered."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.remote = base / "remote.git"
        self.repo = base / "repo"
        self.worktree = base / "feature-worktree"
        self.integration_worktree = base / "integration"
        self.verifier_path = base / "verify.sh"

        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(self.remote)],
            check=True, capture_output=True, text=True,
        )
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Integration Worktree Test")
        git(self.repo, "config", "user.email", "integration@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        (self.repo / "swarm-config.json").write_text(
            json.dumps({"landing": {"integration_worktree": str(self.integration_worktree)}}),
            encoding="utf-8",
        )
        self.verifier_path.write_text(PASS_VERIFIER, encoding="utf-8")
        self.verifier_path.chmod(0o755)
        manifest_path = self.repo / ".agent-plugins/bento/bento/land-work/verifier.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"schema_version": 1, "command": [str(self.verifier_path)], "verified_noop": []}),
            encoding="utf-8",
        )
        git(self.repo, "add", "README.md", "swarm-config.json", str(manifest_path.relative_to(self.repo)))
        git(self.repo, "commit", "-m", "initial commit")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-u", "origin", "main")

        git(self.repo, "worktree", "add", "-b", "feature/test", str(self.worktree), "main")
        (self.worktree / "feature.txt").write_text("feature\n", encoding="utf-8")
        git(self.worktree, "add", "feature.txt")
        git(self.worktree, "commit", "-m", "feature change")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_lands_against_a_persistent_integration_worktree(self) -> None:
        run_env = dict(os.environ)
        result = subprocess.run(
            [str(LAND_SCRIPT)], cwd=self.worktree, capture_output=True, text=True, env=run_env, check=False,
        )
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        step_names = [s["step"] for s in payload["steps"]]
        # cleanup still runs (a documented no-op against the persistent
        # worktree) but verify_landing must not be passed --preview-dir.
        self.assertIn("verify_landing", step_names)
        self.assertTrue((self.repo / "feature.txt").exists())
        # The persistent integration worktree is still registered afterward
        # -- it is meant to survive across landings, not be removed.
        listing = git(self.repo, "worktree", "list", "--porcelain").stdout
        self.assertIn(str(self.integration_worktree.resolve()), listing)


class VerifierFailureTest(LandDriverTestBase):
    def test_verifier_failure_leaves_no_preview_and_does_not_land(self) -> None:
        self.install_verifier(FAILED_VERIFIER)
        original_main = git(self.repo, "rev-parse", "HEAD").stdout.strip()

        result = self.run_driver()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "verify")
        step_names = [s["step"] for s in payload["steps"]]
        self.assertEqual(step_names, ["prepare", "fetch", "create_preview", "verify", "cleanup"])

        # Nothing landed: primary main untouched, feature content absent.
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), original_main)
        self.assertFalse((self.repo / "feature.txt").exists())
        self.assertEqual(self.registered_preview_worktrees(), [])


class SigintDuringMergeTest(LandDriverTestBase):
    def test_sigint_during_merge_leaves_no_preview_and_no_partial_merge(self) -> None:
        # BENTO_LAND_TEST_DELAY_MERGE is a test-only seam (see land.py) that
        # pauses right before the merge command runs, so this test can
        # deterministically land a SIGINT inside the merge_push step instead
        # of racing real git timing.
        original_main = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        env = {"BENTO_LAND_TEST_DELAY_MERGE": "1.5"}
        run_env = dict(os.environ)
        run_env.update(env)
        proc = subprocess.Popen(
            [str(LAND_SCRIPT)], cwd=self.worktree, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=run_env,
        )

        def _send_sigint() -> None:
            time.sleep(0.6)
            proc.send_signal(signal.SIGINT)

        threading.Thread(target=_send_sigint).start()
        stdout, _stderr = proc.communicate(timeout=20)

        self.assertEqual(proc.returncode, 128 + signal.SIGINT)
        payload = json.loads(stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "interrupted")

        # No stale preview worktree, and the primary was never advanced or
        # left mid-merge.
        self.assertEqual(self.registered_preview_worktrees(), [])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), original_main)
        self.assertFalse((self.repo / ".git" / "MERGE_HEAD").exists())
        status = git(self.repo, "status", "--porcelain=v1").stdout.strip()
        self.assertEqual(status, "")


if __name__ == "__main__":
    unittest.main()
