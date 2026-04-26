import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/closure/scripts/closure-scan.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "closure_scan",
        REPO_ROOT / "catalog/skills/closure/scripts/closure-scan.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, env=merged_env)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd)


def git_with_env(cwd: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, env=env)


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
        result = run([str(SCRIPT), *args], self.repo)
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


class ActiveSecondsElapsedTest(unittest.TestCase):
    """Tests for the overnight-aware active_seconds_elapsed function."""

    def setUp(self):
        self.mod = _load_module()

    def _ts(self, hour: int, minute: int = 0, day_offset: int = 0) -> float:
        base = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        return (base + timedelta(days=day_offset)).timestamp()

    def test_overnight_gap_excluded(self):
        # 10:45pm → 8:15am next morning: 15 min before midnight + 15 min after 8am = 30 min
        last = self._ts(22, 45, day_offset=-1)
        now  = self._ts(8, 15, day_offset=0)
        result = self.mod.active_seconds_elapsed(last, now)
        self.assertAlmostEqual(result, 1800, delta=60)

    def test_same_day_active_window(self):
        # 1pm → 3pm: fully within active window, 2 hours
        last = self._ts(13, 0)
        now  = self._ts(15, 0)
        result = self.mod.active_seconds_elapsed(last, now)
        self.assertAlmostEqual(result, 7200, delta=5)

    def test_straddles_end_of_active_window(self):
        # 11:30pm → 9am: 11:30pm is already past the 11pm active-window end,
        # so 0 active minutes before midnight; only 8am–9am = 1 hour counts.
        last = self._ts(23, 30, day_offset=-1)
        now  = self._ts(9, 0, day_offset=0)
        result = self.mod.active_seconds_elapsed(last, now)
        self.assertAlmostEqual(result, 3600, delta=60)

    def test_start_inside_inactive_window(self):
        # 2am → 10am: the 2am–8am gap is inactive; only 8am–10am = 2 hours counts
        last = self._ts(2, 0)
        now  = self._ts(10, 0)
        result = self.mod.active_seconds_elapsed(last, now)
        self.assertAlmostEqual(result, 7200, delta=5)

    def test_zero_elapsed_when_equal(self):
        ts = self._ts(14, 0)
        self.assertEqual(self.mod.active_seconds_elapsed(ts, ts), 0.0)

    def test_zero_elapsed_when_last_after_now(self):
        last = self._ts(15, 0)
        now  = self._ts(14, 0)
        self.assertEqual(self.mod.active_seconds_elapsed(last, now), 0.0)


class MergedCheckedOutTest(unittest.TestCase):
    """Tests for the merged_checked_out branch classification."""

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
        path.write_text(content, encoding="utf-8")
        git(self.repo, "add", relative_path)
        git(self.repo, "commit", "-m", message)
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def commit_file_with_old_date(self, relative_path: str, content: str, message: str) -> str:
        path = self.repo / relative_path
        path.write_text(content, encoding="utf-8")
        git(self.repo, "add", relative_path)
        old_date = "2020-01-01T12:00:00+00:00"
        git_with_env(
            self.repo,
            {
                "GIT_AUTHOR_DATE": old_date,
                "GIT_COMMITTER_DATE": old_date,
            },
            "commit",
            "-m",
            message,
        )
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def run_scan(self, *args: str) -> dict:
        return json.loads(run([str(SCRIPT), "--no-liveness", *args], self.repo).stdout)

    def branch_record(self, scan: dict, branch_name: str) -> dict:
        for branch in scan["local_branches"]:
            if branch["name"] == branch_name:
                return branch
        self.fail(f"missing branch record for {branch_name}")

    def test_merged_branch_in_worktree_classified_as_merged_checked_out(self) -> None:
        # Create and merge a feature branch, then add a linked worktree for it.
        # The branch should be classified as merged_checked_out, not
        # checked_out_in_worktree, so the agent knows the work is already landed.
        git(self.repo, "checkout", "-b", "feature-done")
        self.commit_file("done.txt", "done\n", "add done work")
        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "--no-ff", "feature-done", "-m", "merge feature-done")

        worktree_path = Path(self.temp_dir.name) / "wt-done"
        git(self.repo, "worktree", "add", str(worktree_path), "feature-done")

        scan = self.run_scan()

        rec = self.branch_record(scan, "feature-done")
        self.assertEqual(rec["classification"], "merged_checked_out")
        self.assertTrue(rec["merged_into_primary"])
        self.assertTrue(rec["checked_out_in_worktree"])
        self.assertIn("feature-done", scan["summary"]["merged_checked_out_local_branches"])
        self.assertNotIn("feature-done", scan["summary"]["checked_out_local_branches"])

    def test_unmerged_branch_in_worktree_still_checked_out_classification(self) -> None:
        git(self.repo, "checkout", "-b", "feature-wip")
        self.commit_file("wip.txt", "wip\n", "add wip")
        git(self.repo, "checkout", "main")

        worktree_path = Path(self.temp_dir.name) / "wt-wip"
        git(self.repo, "worktree", "add", str(worktree_path), "feature-wip")

        scan = self.run_scan()

        rec = self.branch_record(scan, "feature-wip")
        self.assertEqual(rec["classification"], "checked_out_in_worktree")
        self.assertFalse(rec["merged_into_primary"])
        self.assertIn("feature-wip", scan["summary"]["checked_out_local_branches"])
        self.assertNotIn("feature-wip", scan["summary"]["merged_checked_out_local_branches"])

    def test_no_liveness_flag_skips_liveness_field(self) -> None:
        scan = self.run_scan("--no-liveness")
        for wt in scan["worktrees"]:
            self.assertNotIn("liveness", wt)

    def test_worktree_dirty_state_reported(self) -> None:
        # Create a branch and linked worktree, then dirty a tracked file in it.
        git(self.repo, "checkout", "-b", "feature-dirty")
        self.commit_file("dirty.txt", "original\n", "add dirty file")
        git(self.repo, "checkout", "main")

        worktree_path = Path(self.temp_dir.name) / "wt-dirty"
        git(self.repo, "worktree", "add", str(worktree_path), "feature-dirty")
        (worktree_path / "dirty.txt").write_text("modified\n", encoding="utf-8")

        scan = self.run_scan("--no-liveness")
        wt_records = {wt["path"]: wt for wt in scan["worktrees"]}
        linked = wt_records.get(str(worktree_path))
        self.assertIsNotNone(linked)
        self.assertTrue(linked["working_tree_dirty"])

    def test_apply_removes_clean_stale_merged_worktree_then_branch(self) -> None:
        git(self.repo, "checkout", "-b", "feature-done")
        self.commit_file_with_old_date("done.txt", "done\n", "add done work")
        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "--no-ff", "feature-done", "-m", "merge feature-done")

        worktree_path = Path(self.temp_dir.name) / "wt-done"
        git(self.repo, "worktree", "add", str(worktree_path), "feature-done")

        scan = json.loads(run([str(SCRIPT), "--apply", "delete-local-merged-branches"], self.repo).stdout)
        branches = git(self.repo, "branch", "--format=%(refname:short)").stdout.splitlines()

        self.assertIn(
            {
                "action": "delete_worktree",
                "branch": "feature-done",
                "worktree": str(worktree_path),
            },
            scan["applied_actions"],
        )
        self.assertIn(
            {"action": "delete_local_branch", "branch": "feature-done"},
            scan["applied_actions"],
        )
        self.assertFalse(worktree_path.exists())
        self.assertNotIn("feature-done", branches)

    def test_apply_keeps_recently_active_merged_worktree_and_branch(self) -> None:
        git(self.repo, "checkout", "-b", "feature-recent")
        self.commit_file("recent.txt", "recent\n", "add recent work")
        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "--no-ff", "feature-recent", "-m", "merge feature-recent")

        worktree_path = Path(self.temp_dir.name) / "wt-recent"
        git(self.repo, "worktree", "add", str(worktree_path), "feature-recent")

        scan = json.loads(run([str(SCRIPT), "--apply", "delete-local-merged-branches"], self.repo).stdout)
        branches = git(self.repo, "branch", "--format=%(refname:short)").stdout.splitlines()

        self.assertIn(
            {
                "action": "delete_worktree",
                "branch": "feature-recent",
                "worktree": str(worktree_path),
                "reason": "worktree liveness is recently_active",
            },
            scan["skipped_actions"],
        )
        self.assertIn(
            {
                "action": "delete_local_branch",
                "branch": "feature-recent",
                "reason": "branch still checked out in a retained worktree",
            },
            scan["skipped_actions"],
        )
        self.assertTrue(worktree_path.exists())
        self.assertIn("feature-recent", branches)

    def test_apply_keeps_dirty_merged_worktree_and_branch(self) -> None:
        git(self.repo, "checkout", "-b", "feature-dirty-merged")
        self.commit_file_with_old_date("dirty-merged.txt", "original\n", "add merged dirty file")
        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "--no-ff", "feature-dirty-merged", "-m", "merge feature-dirty-merged")

        worktree_path = Path(self.temp_dir.name) / "wt-dirty-merged"
        git(self.repo, "worktree", "add", str(worktree_path), "feature-dirty-merged")
        (worktree_path / "dirty-merged.txt").write_text("modified\n", encoding="utf-8")

        scan = json.loads(run([str(SCRIPT), "--apply", "delete-local-merged-branches"], self.repo).stdout)
        branches = git(self.repo, "branch", "--format=%(refname:short)").stdout.splitlines()

        self.assertIn(
            {
                "action": "delete_worktree",
                "branch": "feature-dirty-merged",
                "worktree": str(worktree_path),
                "reason": "worktree has uncommitted changes",
            },
            scan["skipped_actions"],
        )
        self.assertIn(
            {
                "action": "delete_local_branch",
                "branch": "feature-dirty-merged",
                "reason": "branch still checked out in a retained worktree",
            },
            scan["skipped_actions"],
        )
        self.assertTrue(worktree_path.exists())
        self.assertIn("feature-dirty-merged", branches)


LAUNCH_WORK_LOG_BODY = """<!-- launch-work-log
last-updated: 2026-04-26T12:00:00Z
checkpoint: {checkpoint}
-->

# Launch-Work Progress Log

## Next action
do the thing
"""


class ClosureScanLaunchWorkLogTest(unittest.TestCase):
    """closure-scan reports a launch_work field on worktrees that contain
    .launch-work/log.md."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Closure Test")
        git(self.repo, "config", "user.email", "closure@example.com")
        write_file(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_worktree_with_log(self, branch: str, *, checkpoint: str) -> Path:
        wt = Path(self.temp_dir.name) / f"wt-{branch}"
        git(self.repo, "worktree", "add", "-b", branch, str(wt), "main")
        git(wt, "config", "user.name", "Closure Test")
        git(wt, "config", "user.email", "closure@example.com")
        log_path = wt / ".launch-work" / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(LAUNCH_WORK_LOG_BODY.format(checkpoint=checkpoint), encoding="utf-8")
        git(wt, "add", ".launch-work/log.md")
        git(wt, "commit", "-m", "chore(launch-work-log): " + checkpoint)
        return wt

    def _scan(self) -> dict:
        return json.loads(run([str(SCRIPT), "--no-liveness"], self.repo).stdout)

    def _worktree_record(self, scan: dict, path: Path) -> dict:
        for wt in scan["worktrees"]:
            if wt["path"] == str(path):
                return wt
        self.fail(f"missing worktree record for {path}")

    def test_launch_work_field_present_when_log_exists(self) -> None:
        wt = self._make_worktree_with_log("feature-active", checkpoint="tests-green")

        scan = self._scan()
        record = self._worktree_record(scan, wt)

        self.assertIn("launch_work", record)
        self.assertEqual(
            record["launch_work"],
            {
                "present": True,
                "last_updated": "2026-04-26T12:00:00Z",
                "checkpoint": "tests-green",
            },
        )

    def test_launch_work_field_absent_when_log_missing(self) -> None:
        wt = Path(self.temp_dir.name) / "wt-plain"
        git(self.repo, "worktree", "add", "-b", "feature-plain", str(wt), "main")

        scan = self._scan()
        record = self._worktree_record(scan, wt)
        self.assertNotIn("launch_work", record)


class ClosureApplyLaunchWorkExclusionTest(unittest.TestCase):
    """A worktree with an in-flight launch-work log (checkpoint != ready-to-land)
    is never eligible for --apply delete-local-merged-branches, even when the
    branch is merged and the worktree is otherwise clean."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Closure Test")
        git(self.repo, "config", "user.email", "closure@example.com")
        write_file(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_in_flight_log_blocks_auto_delete(self) -> None:
        # Build a merged branch whose commit set includes the log file, then
        # add a linked worktree on the merged branch. This represents the
        # defensive case: land-work normally removes the log before merge, but
        # if a log somehow survives, closure must not auto-delete the worktree.
        old_date = "2020-01-01T12:00:00+00:00"
        old_env = {"GIT_AUTHOR_DATE": old_date, "GIT_COMMITTER_DATE": old_date}

        git(self.repo, "checkout", "-b", "feature-active")
        write_file(self.repo / "work.txt", "work\n")
        git(self.repo, "add", "work.txt")
        git_with_env(self.repo, old_env, "commit", "-m", "add work")

        log_path = self.repo / ".launch-work" / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            LAUNCH_WORK_LOG_BODY.format(checkpoint="tests-green"), encoding="utf-8"
        )
        git(self.repo, "add", ".launch-work/log.md")
        git_with_env(self.repo, old_env, "commit", "-m", "chore(launch-work-log): tests-green")

        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "--no-ff", "feature-active", "-m", "merge feature-active")

        wt = Path(self.temp_dir.name) / "wt-feature-active"
        git(self.repo, "worktree", "add", str(wt), "feature-active")

        scan = json.loads(
            run([str(SCRIPT), "--apply", "delete-local-merged-branches"], self.repo).stdout
        )
        branches = git(self.repo, "branch", "--format=%(refname:short)").stdout.splitlines()

        self.assertIn(
            {
                "action": "delete_worktree",
                "branch": "feature-active",
                "worktree": str(wt),
                "reason": "launch-work log in flight (checkpoint=tests-green)",
            },
            scan["skipped_actions"],
        )
        self.assertTrue(wt.exists())
        self.assertIn("feature-active", branches)


if __name__ == "__main__":
    unittest.main()
