import json
import os
import signal
import subprocess
import sys
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
        # otherwise the feature branch would be behind primary by this commit.
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
            env=run_env, check=check, stdin=subprocess.DEVNULL,
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
            ["prepare", "fetch", "create_preview", "verify", "lease_check", "merge_push", "cleanup", "verify_landing", "teardown"],
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


class PreviewOwnershipTest(LandDriverTestBase):
    @unittest.skipUnless(Path("/proc/self/stat").exists(), "needs /proc")
    def test_driver_records_its_pid_as_preview_owner(self) -> None:
        # The verifier runs while the preview exists: capture its owner file
        # and its ancestor pids (land.py is one of them).
        out = Path(self.temp_dir.name) / "owner-capture"
        self.install_verifier(
            "#!/usr/bin/env bash\n"
            f'cp "$(git rev-parse --absolute-git-dir)/land-work-owner.json" {out}.json\n'
            f'p=$$; while [ "$p" -gt 1 ]; do echo $p >> {out}.pids; '
            'p=$(awk \'{print $4}\' /proc/$p/stat); done\n'
            + PASS_VERIFIER.split("\n", 1)[1]
        )
        result = self.run_driver()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        owner = json.loads(Path(f"{out}.json").read_text(encoding="utf-8"))
        self.assertEqual(owner["owner_kind"], "driver")
        self.assertIn(str(owner["pid"]), Path(f"{out}.pids").read_text().split())
        self.assertNotEqual(owner["pid"], os.getpid())

    def test_driver_reclaims_dead_driver_leftover(self) -> None:
        proc = subprocess.Popen(["true"])
        proc.wait()
        created = run(
            [str(CREATE_PREVIEW_SCRIPT), "--owner-pid", str(proc.pid)], self.worktree,
        )
        leftover = json.loads(created.stdout)["preview_dir"]
        # The pid was already gone at creation, so no start time was recorded
        # (unobservable => unknown); record the one a live driver would have.
        owner_file = Path(git(leftover, "rev-parse", "--absolute-git-dir").stdout.strip()) / "land-work-owner.json"
        owner = json.loads(owner_file.read_text(encoding="utf-8"))
        owner["pid_start_time"] = "1"
        owner_file.write_text(json.dumps(owner), encoding="utf-8")
        self.assertEqual(self.registered_preview_worktrees(), [leftover])

        result = self.run_driver()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(Path(leftover).exists())
        self.assertEqual(self.registered_preview_worktrees(), [])


class BehindFeatureBranchTest(LandDriverTestBase):
    def advance_primary(self, name: str, content: str = "main\n", count: int = 3) -> None:
        for i in range(count):
            (self.repo / f"{name}{i}.txt").write_text(content, encoding="utf-8")
            git(self.repo, "add", f"{name}{i}.txt")
            git(self.repo, "commit", "-m", f"main advance {i}")
        git(self.repo, "push", "origin", "main")

    def test_behind_branch_with_clean_preview_lands_without_rebase(self) -> None:
        self.advance_primary("other")
        feature_tip = git(self.worktree, "rev-parse", "HEAD").stdout.strip()

        result = self.run_driver()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        parent2 = git(self.repo, "rev-parse", "HEAD^2").stdout.strip()
        self.assertEqual(parent2, feature_tip)
        self.assertTrue((self.repo / "other0.txt").exists())
        self.assertTrue((self.repo / "feature.txt").exists())

    def test_verifier_sees_merged_candidate_and_only_feature_paths(self) -> None:
        # Exempt the feature's only changed path and have the verifier select
        # zero checks. With a feature-only diff nothing relevant remains and
        # the landing passes; a two-dot diff against the advanced base would
        # also list main-only files as unverified and fail.
        manifest_path = self.repo / ".agent-plugins/bento/bento/land-work/verifier.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["verified_noop"] = [{"path": "feature.txt", "reason": "test"}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        git(self.repo, "commit", "-am", "exempt feature.txt")
        git(self.repo, "push", "origin", "main")
        git(self.worktree, "merge", "main", "-m", "sync manifest")
        self.advance_primary("other")
        self.install_verifier(
            "#!/usr/bin/env bash\n"
            'echo \'{"schema_version":1,"status":"passed","selected_checks":[]}\'\n'
        )

        result = self.run_driver()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_verifier_runs_in_candidate_with_main_and_feature_files(self) -> None:
        self.advance_primary("other")
        seen = Path(self.temp_dir.name) / "seen"
        self.install_verifier(
            "#!/usr/bin/env bash\n"
            f"ls other0.txt feature.txt > {seen}\n" + PASS_VERIFIER.split("\n", 1)[1]
        )
        result = self.run_driver()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(seen.read_text().split(), ["feature.txt", "other0.txt"])

    def test_conflicting_branch_reports_rebase_required(self) -> None:
        self.advance_primary("shared", content="main version\n", count=1)
        # main now also adds shared0.txt; make the feature touch the same path.
        (self.worktree / "shared0.txt").write_text("feature version\n", encoding="utf-8")
        git(self.worktree, "add", "shared0.txt")
        git(self.worktree, "commit", "-m", "conflicting feature change")
        main_before = git(self.repo, "rev-parse", "HEAD").stdout.strip()

        result = self.run_driver()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "create_preview")
        self.assertIn("rebase onto origin/main, resolve, and re-run land.py", payload["error"])
        self.assertIn("shared0.txt", payload["error"])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), main_before)
        self.assertEqual(self.registered_preview_worktrees(), [])


class PushFromPreviewRouteTest(LandDriverTestBase):
    def test_ahead_primary_uses_push_from_preview_route(self) -> None:
        # Simulate the primary's local main gaining a commit the leased
        # remote doesn't have yet (bento-rdtn.5's "ahead" diagnostic),
        # deliberately never pushed. Rebase the feature branch onto it so the
        # feature branch itself is not behind the local primary --
        # primary_local_vs_remote is a separate, orthogonal check from
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
        # prepare could have caught), the
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
        # branch itself is not behind; the primary checkout's local main is still stale.
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


class VerifierTreeReuseDriverTest(LandDriverTestBase):
    """bento-c96u.2: a green record for the candidate tree is reused."""

    def setUp(self) -> None:
        super().setUp()
        self.counter = Path(self.temp_dir.name) / "counter"
        self.install_counting(PASS_VERIFIER)

    def install_counting(self, content: str) -> None:
        body = content.split("\n", 1)[1]
        self.install_verifier(f"#!/usr/bin/env bash\necho x >> {self.counter}\n{body}")

    def runs(self) -> int:
        return len(self.counter.read_text().splitlines()) if self.counter.exists() else 0

    def pre_verify_feature(self) -> None:
        # Feature is based on the leased tip, so its HEAD tree equals the
        # future merge tree; verifying it ahead of landing produces the record.
        head = git(self.worktree, "rev-parse", "HEAD").stdout.strip()
        base = git(self.worktree, "rev-parse", "main").stdout.strip()
        result = subprocess.run(
            [str(REPO_ROOT / "catalog/skills/land-work/scripts/land-work-run-verifier.py"),
             "--repo-root", str(self.worktree), "--candidate", str(self.worktree),
             "--base-sha", base, "--head-sha", head,
             "--log", str(Path(self.temp_dir.name) / "pre-verify.log")],
            capture_output=True, text=True, cwd=self.worktree, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.runs(), 1)

    def test_identical_tree_landing_reuses_record_and_skips_verifier(self) -> None:
        self.pre_verify_feature()
        result = self.run_driver()
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.runs(), 1)
        verify_step = next(s for s in payload["steps"] if s["step"] == "verify")
        self.assertTrue(verify_step["reused"])
        self.assertNotIn("cached", verify_step)
        self.assertIn("verify: passed", result.stderr)
        self.assertIn("[reused, not executed]", result.stderr)

    def test_changed_tree_reruns_verifier(self) -> None:
        self.pre_verify_feature()
        (self.worktree / "more.txt").write_text("more\n", encoding="utf-8")
        git(self.worktree, "add", "more.txt")
        git(self.worktree, "commit", "-m", "more")
        result = self.run_driver()
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.runs(), 2)
        verify_step = next(s for s in payload["steps"] if s["step"] == "verify")
        self.assertNotIn("reused", verify_step)
        self.assertIn("[executed]", result.stderr)

    def test_advanced_base_changes_preview_tree_and_reruns(self) -> None:
        self.pre_verify_feature()
        (self.repo / "other.txt").write_text("o\n", encoding="utf-8")
        git(self.repo, "add", "other.txt")
        git(self.repo, "commit", "-m", "main advance")
        git(self.repo, "push", "origin", "main")
        result = self.run_driver()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.runs(), 2)
        self.assertNotIn("reused", result.stderr)

    def test_stale_record_still_passes_flag_and_executes(self) -> None:
        self.pre_verify_feature()
        store = Path(git(self.worktree, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()) / "bento" / "gate-evidence"
        for record_path in store.glob("*.json"):
            record = json.loads(record_path.read_text())
            record["recorded_at"] = "2020-01-01T00:00:00+00:00"
            record_path.write_text(json.dumps(record))
        result = self.run_driver()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.runs(), 2)
        self.assertIn("[executed]", result.stderr)

    def test_project_reported_all_cached_still_rejected(self) -> None:
        self.install_counting(
            '#!/usr/bin/env bash\n'
            'echo \'{"schema_version":1,"status":"passed",'
            '"selected_checks":[{"name":"t","status":"passed","executed":false}]}\'\n'
        )
        result = self.run_driver()
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["failed_step"], "verify")
        self.assertIn("executed: false", payload["error"])


class NoMergeCanaryTest(LandDriverTestBase):
    """bento-c96u.15: --no-merge runs the real sequence and stops before merge."""

    def run_driver(self, *args: str, env: dict | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
        # Independent of the caller's env: drop any test seams a parent set.
        clean = {k: v for k, v in os.environ.items() if not k.startswith("BENTO_LAND_TEST_")}
        clean.update(env or {})
        return subprocess.run(
            [str(LAND_SCRIPT), *args], cwd=self.worktree, capture_output=True, text=True, env=clean, check=check,
            stdin=subprocess.DEVNULL,
        )

    def remote_main(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", "refs/heads/main"], cwd=self.remote, capture_output=True, text=True, check=True,
        ).stdout.strip()

    def evidence_records(self) -> list[Path]:
        store = Path(git(self.worktree, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()) / "bento" / "gate-evidence"
        return list(store.glob("*.json")) if store.exists() else []

    def test_good_branch_reports_every_step_and_touches_nothing(self) -> None:
        main_before = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        remote_before = self.remote_main()
        result = self.run_driver("--no-merge")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "no-merge")
        self.assertIs(payload["merged"], False)
        self.assertTrue(payload["preview_tree"])
        self.assertEqual(
            [s["step"] for s in payload["steps"]],
            ["prepare", "fetch", "create_preview", "verify", "lease_check", "cleanup"],
        )
        self.assertTrue(all(s["status"] == "passed" for s in payload["steps"]))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), main_before)
        self.assertEqual(self.remote_main(), remote_before)
        self.assertFalse((self.repo / "feature.txt").exists())
        self.assertEqual(git(self.repo, "status", "--porcelain=v1").stdout.strip(), "")
        self.assertEqual(self.registered_preview_worktrees(), [])

    def test_never_writes_evidence_record(self) -> None:
        self.assertEqual(self.run_driver("--no-merge").returncode, 0)
        self.assertEqual(self.evidence_records(), [])

    def test_never_reuses_evidence_record(self) -> None:
        # A real landing's record must not let the canary skip the verifier.
        counter = Path(self.temp_dir.name) / "counter"
        self.install_verifier(f"#!/usr/bin/env bash\necho x >> {counter}\n" + PASS_VERIFIER.split("\n", 1)[1])
        head = git(self.worktree, "rev-parse", "HEAD").stdout.strip()
        base = git(self.worktree, "rev-parse", "main").stdout.strip()
        subprocess.run(
            [str(REPO_ROOT / "catalog/skills/land-work/scripts/land-work-run-verifier.py"),
             "--repo-root", str(self.worktree), "--candidate", str(self.worktree),
             "--base-sha", base, "--head-sha", head, "--log", str(Path(self.temp_dir.name) / "pre.log")],
            capture_output=True, text=True, cwd=self.worktree, check=True,
        )
        self.assertEqual(len(counter.read_text().splitlines()), 1)
        result = self.run_driver("--no-merge")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(counter.read_text().splitlines()), 2)
        self.assertNotIn("reused", result.stderr)

    def test_verifier_failure_fails_at_verify(self) -> None:
        self.install_verifier(FAILED_VERIFIER)
        result = self.run_driver("--no-merge")
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_step"], "verify")
        self.assertEqual(payload["mode"], "no-merge")
        self.assertIs(payload["merged"], False)
        self.assertEqual([s["step"] for s in payload["steps"]][-2:], ["verify", "cleanup"])
        self.assertEqual(self.registered_preview_worktrees(), [])

    def test_moved_lease_fails_at_lease_check(self) -> None:
        other = Path(self.temp_dir.name) / "other-clone"
        subprocess.run(["git", "clone", str(self.remote), str(other)], check=True, capture_output=True, text=True)
        git(other, "config", "user.name", "Other")
        git(other, "config", "user.email", "other@example.com")
        (other / "moved.txt").write_text("m\n", encoding="utf-8")
        git(other, "add", "moved.txt")
        git(other, "commit", "-m", "moves the lease")
        # The verifier (running mid-sequence) pushes a new main and refreshes
        # the remote-tracking ref, as a concurrent landing would.
        self.install_verifier(
            "#!/usr/bin/env bash\n"
            f'git -C {other} push -q origin main && git fetch -q origin main\n'
            + PASS_VERIFIER.split("\n", 1)[1]
        )
        result = self.run_driver("--no-merge")
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(payload["failed_step"], "lease_check")
        self.assertIs(payload.get("merged"), False)
        self.assertEqual(self.registered_preview_worktrees(), [])

    def _interrupt(self, sig: int) -> tuple[int, dict]:
        started = Path(self.temp_dir.name) / f"verifier-started-{sig}"
        self.install_verifier(f"#!/usr/bin/env bash\ntouch {started}\nexec sleep 4\n")
        clean = {k: v for k, v in os.environ.items() if not k.startswith("BENTO_LAND_TEST_")}
        proc = subprocess.Popen(
            [str(LAND_SCRIPT), "--no-merge"], cwd=self.worktree, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=clean,
        )
        deadline = time.monotonic() + 15
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(started.exists())
        proc.send_signal(sig)
        stdout, _stderr = proc.communicate(timeout=20)
        return proc.returncode, json.loads(stdout)

    def test_sigint_cleans_up_preview(self) -> None:
        main_before = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        code, payload = self._interrupt(signal.SIGINT)
        self.assertEqual(code, 128 + signal.SIGINT)
        self.assertEqual(payload["failed_step"], "interrupted")
        self.assertEqual(payload["mode"], "no-merge")
        self.assertIs(payload["merged"], False)
        self.assertEqual(self.registered_preview_worktrees(), [])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").stdout.strip(), main_before)

    def test_sigterm_cleans_up_preview(self) -> None:
        code, payload = self._interrupt(signal.SIGTERM)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(payload["failed_step"], "interrupted")
        self.assertEqual(self.registered_preview_worktrees(), [])

    def test_never_aborts_an_operators_merge_in_the_primary(self) -> None:
        # An in-progress merge in the primary is the operator's; the canary's
        # failure/signal paths must not `git merge --abort` it. (prepare
        # normally refuses a mid-merge primary, so drive the Driver directly.)
        git(self.repo, "checkout", "-q", "-b", "side")
        (self.repo / "clash.txt").write_text("side\n", encoding="utf-8")
        git(self.repo, "add", "clash.txt")
        git(self.repo, "commit", "-m", "side")
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "clash.txt").write_text("main\n", encoding="utf-8")
        git(self.repo, "add", "clash.txt")
        git(self.repo, "commit", "-m", "main clash")
        subprocess.run(["git", "merge", "side"], cwd=self.repo, capture_output=True, text=True)
        merge_head = self.repo / ".git" / "MERGE_HEAD"
        self.assertTrue(merge_head.exists())
        # Fresh interpreter: other test modules put a different git_state on
        # sys.path/sys.modules.
        probe = (
            "import sys; sys.path.insert(0, sys.argv[1]); import land, pathlib; "
            "d = land.Driver(pathlib.Path('.'), 'unknown', None, no_merge=%s); "
            "d.primary_root = pathlib.Path(sys.argv[2]); d.abort_primary_merge_if_in_progress()"
        )
        scripts = str(LAND_SCRIPT.parent)
        for no_merge, expect_present in (("True", True), ("False", False)):
            subprocess.run(
                [sys.executable, "-c", probe % no_merge, scripts, str(self.repo)],
                cwd=self.worktree, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True,
            )
            self.assertEqual(merge_head.exists(), expect_present)


class VerifierEvidenceFlagsTest(unittest.TestCase):
    def test_reuse_and_no_record_are_mutually_exclusive(self) -> None:
        result = subprocess.run(
            [str(REPO_ROOT / "catalog/skills/land-work/scripts/land-work-run-verifier.py"),
             "--repo-root", ".", "--candidate", ".", "--base-sha", "a", "--head-sha", "b",
             "--reuse-evidence", "--no-record-evidence"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("mutually exclusive", result.stderr)


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


class TeardownTest(LandDriverTestBase):
    """bento-c96u.16: after a verified landing land.py removes the feature
    worktree and branch (from the primary checkout) and sweeps LSP residue."""

    def run_driver(self, *args: str, env: dict | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("BENTO_LAND_")}
        clean.update(env or {})
        return subprocess.run(
            [str(LAND_SCRIPT), *args], cwd=self.worktree, capture_output=True, text=True, env=clean,
            check=check, stdin=subprocess.DEVNULL,
        )

    def branches(self) -> list[str]:
        return git(self.repo, "branch", "--list", "--format=%(refname:short)", "feature/test").stdout.split()

    def after_removal(self, action) -> threading.Thread:
        """Run `action` as soon as the feature worktree directory disappears."""
        def _watch() -> None:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if not self.worktree.exists():
                    action()
                    return
                time.sleep(0.005)
        thread = threading.Thread(target=_watch)
        thread.start()
        return thread

    def test_successful_landing_removes_worktree_and_branch(self) -> None:
        result = self.run_driver()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertFalse(self.worktree.exists())
        self.assertEqual(self.branches(), [])
        self.assertNotIn(str(self.worktree), git(self.repo, "worktree", "list").stdout)
        teardown = payload["teardown"]
        self.assertEqual(teardown["status"], "removed")
        self.assertEqual(teardown["worktree"], str(self.worktree.resolve()))
        self.assertEqual(teardown["branch"], "feature/test")
        self.assertTrue(teardown["branch_deleted"])
        self.assertEqual(teardown["cd"], str(self.repo.resolve()))
        # The landing itself is intact.
        self.assertEqual((self.repo / "feature.txt").read_text(encoding="utf-8"), "feature\n")

    def test_dirty_worktree_is_kept_and_run_still_succeeds(self) -> None:
        def _dirty_when_prepared() -> None:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self.registered_preview_worktrees():
                    (self.worktree / "scratch.txt").write_text("keep me\n", encoding="utf-8")
                    return
                time.sleep(0.005)

        thread = threading.Thread(target=_dirty_when_prepared)
        thread.start()
        result = self.run_driver(env={"BENTO_LAND_TEST_DELAY_MERGE": "1.5"})
        thread.join()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertTrue((self.worktree / "scratch.txt").exists())
        self.assertEqual(self.branches(), ["feature/test"])
        self.assertEqual(payload["teardown"]["status"], "skipped")
        self.assertIn("scratch.txt", payload["teardown"]["reason"])
        self.assertIn("teardown", result.stderr)
        # Landed regardless.
        self.assertTrue((self.repo / "feature.txt").exists())

    def test_no_teardown_flag_keeps_worktree(self) -> None:
        result = self.run_driver("--no-teardown")
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.worktree.exists())
        self.assertEqual(self.branches(), ["feature/test"])
        self.assertEqual(payload["teardown"]["status"], "skipped")

    def test_canary_never_tears_down(self) -> None:
        result = self.run_driver("--no-merge")
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("teardown", payload)
        self.assertNotIn("teardown", [s["step"] for s in payload["steps"]])
        self.assertTrue(self.worktree.exists())
        self.assertEqual(self.branches(), ["feature/test"])

    def test_failed_landing_never_tears_down(self) -> None:
        self.install_verifier(FAILED_VERIFIER)
        result = self.run_driver()
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("teardown", payload)
        self.assertTrue(self.worktree.exists())
        self.assertEqual(self.branches(), ["feature/test"])

    def test_batch_mode_repo_never_tears_down(self) -> None:
        (self.repo / "swarm-config.json").write_text(json.dumps({"landing": {"mode": "batch"}}), encoding="utf-8")
        git(self.repo, "add", "swarm-config.json")
        git(self.repo, "commit", "-m", "batch mode")
        git(self.repo, "push", "origin", "main")
        git(self.worktree, "rebase", "main")
        result = self.run_driver()
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["teardown"]["status"], "skipped")
        self.assertTrue(self.worktree.exists())

    def test_residue_only_leftover_is_swept(self) -> None:
        def _recreate() -> None:
            flycheck = self.worktree / "target" / "flycheck0"
            flycheck.mkdir(parents=True)
            (flycheck / "stdout").write_text("", encoding="utf-8")
            (flycheck / "stderr").write_text("", encoding="utf-8")

        thread = self.after_removal(_recreate)
        result = self.run_driver(env={"BENTO_LAND_RESIDUE_WAIT": "1.5"})
        thread.join()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.worktree.exists())
        self.assertTrue(payload["teardown"]["residue_removed"])
        self.assertEqual(payload["teardown"]["residue_left"], [])

    def test_leftover_with_real_files_is_not_swept(self) -> None:
        def _recreate() -> None:
            (self.worktree / "src").mkdir(parents=True)
            (self.worktree / "src" / "x.rs").write_text("fn main() {}\n", encoding="utf-8")
            flycheck = self.worktree / "target" / "flycheck0"
            flycheck.mkdir(parents=True)
            (flycheck / "stdout").write_text("", encoding="utf-8")

        thread = self.after_removal(_recreate)
        result = self.run_driver(env={"BENTO_LAND_RESIDUE_WAIT": "1.5"})
        thread.join()
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.worktree / "src" / "x.rs").exists())
        self.assertFalse(payload["teardown"]["residue_removed"])
        self.assertIn("src/x.rs", payload["teardown"]["residue_left"])

    def test_extra_residue_globs_file_extends_allowlist(self) -> None:
        globs = self.repo / ".agent-plugins/bento/bento/land-work/residue-globs.txt"
        globs.write_text("# extra\n.idea/**\n", encoding="utf-8")
        git(self.repo, "add", str(globs.relative_to(self.repo)))
        git(self.repo, "commit", "-m", "residue globs")
        git(self.repo, "push", "origin", "main")
        git(self.worktree, "rebase", "main")

        def _recreate() -> None:
            (self.worktree / ".idea").mkdir(parents=True)
            (self.worktree / ".idea" / "workspace.xml").write_text("", encoding="utf-8")

        thread = self.after_removal(_recreate)
        result = self.run_driver(env={"BENTO_LAND_RESIDUE_WAIT": "1.5", "XDG_CONFIG_HOME": self.temp_dir.name})
        thread.join()
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.worktree.exists())
        self.assertTrue(payload["teardown"]["residue_removed"])
