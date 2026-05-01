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

    def test_self_invocation_flag_set_when_helper_runs_inside_worktree(self) -> None:
        git(self.repo, "checkout", "-b", "feature-self-call")
        self.commit_file("self.txt", "self\n", "add self file")
        git(self.repo, "checkout", "main")

        worktree_path = Path(self.temp_dir.name) / "wt-self-call"
        git(self.repo, "worktree", "add", str(worktree_path), "feature-self-call")

        scan = json.loads(
            run([str(SCRIPT), "--no-liveness"], worktree_path).stdout
        )
        wt_records = {wt["path"]: wt for wt in scan["worktrees"]}

        linked = wt_records[str(worktree_path)]
        self.assertTrue(linked.get("self_invocation"))

        primary = wt_records[str(self.repo)]
        self.assertFalse(primary.get("self_invocation", False))

    def test_self_invocation_skip_reason_points_to_land_work(self) -> None:
        # Self-invocation takes precedence over other skip reasons in
        # removable_merged_worktree_reason; the message must redirect
        # callers to land-work for own-work cleanup.
        mod = _load_module()
        worktree = {
            "path": "/tmp/some-worktree",
            "self_invocation": True,
            "working_tree_dirty": False,
            "liveness": {"verdict": "stale"},
        }
        reason = mod.removable_merged_worktree_reason(worktree, Path("/tmp/elsewhere"))
        self.assertIsNotNone(reason)
        self.assertIn("self-invocation", reason)
        self.assertIn("land-work", reason)

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

    def test_apply_removes_recently_active_merged_worktree_and_branch(self) -> None:
        # The merging agent's own activity (commit, file mtime) makes the
        # just-merged worktree look recently_active. Because the branch is
        # already landed, that recency does not represent a competing agent;
        # closure must still clean the worktree up so the documented
        # land-work -> closure handoff completes immediately.
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
            },
            scan["applied_actions"],
        )
        self.assertIn(
            {"action": "delete_local_branch", "branch": "feature-recent"},
            scan["applied_actions"],
        )
        self.assertFalse(worktree_path.exists())
        self.assertNotIn("feature-recent", branches)

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

    def test_target_branch_scopes_apply_to_one_branch(self) -> None:
        # Two merged feature branches with linked worktrees — only the targeted
        # one should be cleaned up.
        for name in ("feature-target", "feature-other"):
            git(self.repo, "checkout", "-b", name)
            self.commit_file_with_old_date(f"{name}.txt", "x\n", f"add {name}")
            git(self.repo, "checkout", "main")
            git(self.repo, "merge", "--no-ff", name, "-m", f"merge {name}")

        target_wt = Path(self.temp_dir.name) / "wt-target"
        other_wt = Path(self.temp_dir.name) / "wt-other"
        git(self.repo, "worktree", "add", str(target_wt), "feature-target")
        git(self.repo, "worktree", "add", str(other_wt), "feature-other")

        scan = json.loads(
            run(
                [
                    str(SCRIPT),
                    "--target-branch",
                    "feature-target",
                    "--apply",
                    "delete-local-merged-branches",
                ],
                self.repo,
            ).stdout
        )
        branches = git(self.repo, "branch", "--format=%(refname:short)").stdout.splitlines()

        self.assertIn(
            {"action": "delete_worktree", "branch": "feature-target", "worktree": str(target_wt)},
            scan["applied_actions"],
        )
        self.assertIn(
            {"action": "delete_local_branch", "branch": "feature-target"},
            scan["applied_actions"],
        )
        self.assertFalse(target_wt.exists())
        self.assertNotIn("feature-target", branches)
        # The non-targeted merged branch and its worktree must remain untouched.
        self.assertTrue(other_wt.exists())
        self.assertIn("feature-other", branches)
        for action in scan["applied_actions"]:
            self.assertNotIn("feature-other", action.get("branch", ""))

    def test_target_branch_missing_errors_non_zero(self) -> None:
        result = subprocess.run(
            [
                str(SCRIPT),
                "--target-branch",
                "no-such-branch",
                "--apply",
                "delete-local-merged-branches",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no-such-branch", result.stderr)

    def test_target_branch_wrong_classification_skipped(self) -> None:
        # An unmerged branch should not be eligible: the helper reports it in
        # skipped_actions and leaves the branch in place. Exit code is 0 — the
        # caller decides what to do with the skip reason.
        git(self.repo, "checkout", "-b", "feature-open")
        self.commit_file("open.txt", "open\n", "add open work")
        git(self.repo, "checkout", "main")

        scan = json.loads(
            run(
                [
                    str(SCRIPT),
                    "--target-branch",
                    "feature-open",
                    "--apply",
                    "delete-local-merged-branches",
                ],
                self.repo,
            ).stdout
        )
        branches = git(self.repo, "branch", "--format=%(refname:short)").stdout.splitlines()

        self.assertEqual(scan["applied_actions"], [])
        self.assertIn("feature-open", branches)
        skipped_branches = {entry.get("branch") for entry in scan["skipped_actions"]}
        self.assertIn("feature-open", skipped_branches)


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

    def test_launch_work_field_resolved_via_git_dir(self) -> None:
        # The canonical location is <git-dir>/launch-work/log.md, never the
        # working tree. Closure must find a log there even when the working
        # tree has no .launch-work directory.
        wt = Path(self.temp_dir.name) / "wt-git-dir-log"
        git(self.repo, "worktree", "add", "-b", "feature-gd", str(wt), "main")
        git_dir = Path(
            run(["git", "rev-parse", "--absolute-git-dir"], wt).stdout.strip()
        )
        log_path = git_dir / "launch-work" / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            LAUNCH_WORK_LOG_BODY.format(checkpoint="ready-to-land"), encoding="utf-8"
        )

        scan = self._scan()
        record = self._worktree_record(scan, wt)

        self.assertEqual(
            record["launch_work"],
            {
                "present": True,
                "last_updated": "2026-04-26T12:00:00Z",
                "checkpoint": "ready-to-land",
            },
        )
        # Working tree must remain clean — the log lives outside it.
        self.assertFalse((wt / ".launch-work").exists())
        status = run(["git", "status", "--porcelain"], wt).stdout.strip()
        self.assertEqual(status, "")


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


class ClosureScanMissingWorktreeDirTest(unittest.TestCase):
    """closure-scan must not crash when a registered worktree's directory has
    been removed from disk (the prunable state left by interrupted land-work
    runs). It should auto-prune or guard each per-worktree probe so the scan
    completes."""

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

    def test_scan_completes_when_registered_worktree_dir_is_missing(self) -> None:
        wt = Path(self.temp_dir.name) / "wt-ghost"
        git(self.repo, "worktree", "add", "-b", "ghost-branch", str(wt), "main")

        import shutil as _shutil
        _shutil.rmtree(wt)
        self.assertFalse(wt.exists())

        # Without a fix, closure-scan raises FileNotFoundError before git
        # can report the missing worktree, and the whole scan exits non-zero.
        scan = json.loads(run([str(SCRIPT)], self.repo).stdout)

        self.assertIn("worktrees", scan)
        scanned_paths = {w["path"] for w in scan["worktrees"]}
        self.assertNotIn(str(wt), scanned_paths)
        warnings = scan.get("warnings", [])
        self.assertTrue(
            any("pruned" in w and "missing" in w for w in warnings),
            f"expected prune warning, got {warnings}",
        )


class CorrelateBranchesTest(unittest.TestCase):
    """Tests for --correlate-branches signal emission on review_required branches."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Closure Test")
        git(self.repo, "config", "user.email", "closure@example.com")
        self._commit("README.md", "root\n", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _commit(self, rel: str, content: str, msg: str) -> str:
        path = self.repo / rel
        path.write_text(content, encoding="utf-8")
        git(self.repo, "add", rel)
        git(self.repo, "commit", "-m", msg)
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def _scan(self, *args: str) -> dict:
        return json.loads(
            run([str(SCRIPT), "--no-liveness", *args], self.repo).stdout
        )

    def _branch_record(self, scan: dict, name: str) -> dict:
        for b in scan["local_branches"]:
            if b["name"] == name:
                return b
        self.fail(f"missing branch {name}")

    def test_correlate_only_emitted_on_review_required(self) -> None:
        # feature-merged → safe_to_delete (no correlation block)
        # feature-open → review_required (has correlation block)
        git(self.repo, "checkout", "-b", "feature-merged")
        self._commit("merged.txt", "m\n", "add merged")
        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "--no-ff", "feature-merged", "-m", "merge")

        git(self.repo, "checkout", "-b", "bento-999-feature-open")
        self._commit("open.txt", "o\n", "add open work")
        git(self.repo, "checkout", "main")

        scan = self._scan("--correlate-branches", "--tracker", "none")

        merged_rec = self._branch_record(scan, "feature-merged")
        self.assertNotIn("correlation", merged_rec)

        open_rec = self._branch_record(scan, "bento-999-feature-open")
        self.assertIn("correlation", open_rec)

    def test_correlate_signals_for_open_branch(self) -> None:
        git(self.repo, "checkout", "-b", "bento-999-feature-open")
        self._commit("open.txt", "o\n", "add open work")
        self._commit("more.txt", "more\n", "more open work")
        git(self.repo, "checkout", "main")
        self._commit("main-only.txt", "m\n", "main divergence")

        scan = self._scan(
            "--correlate-branches",
            "--tracker", "none",
            "--issue-pattern", r"(bento-[0-9]+)",
        )
        rec = self._branch_record(scan, "bento-999-feature-open")
        corr = rec["correlation"]

        self.assertEqual(corr["issue_id"], "bento-999")
        self.assertEqual(corr["cherry_unique_count"], 2)
        self.assertEqual(corr["cherry_equivalent_count"], 0)
        self.assertEqual(corr["divergence_ahead"], 2)
        self.assertEqual(corr["divergence_behind"], 1)
        self.assertIsNone(corr["tracker_status"])
        self.assertEqual(corr["main_commits_referencing_issue"], [])
        self.assertGreaterEqual(corr["merge_base_age_days"], 0)

    def test_correlate_detects_landed_under_different_sha(self) -> None:
        # Branch with cherry-pick equivalent already on main → all cherry "-"
        # AND main has a commit message mentioning the issue id.
        git(self.repo, "checkout", "-b", "bento-777-landed-elsewhere")
        c = self._commit("landed.txt", "l\n", "add landed bento-777")
        git(self.repo, "checkout", "main")
        self._commit("main-only.txt", "m\n", "main divergence")
        git(self.repo, "cherry-pick", c)

        # cherry-pick of merged branch yields patch_equivalent_review (no
        # correlation). Force review_required by adding an unmerged commit AND
        # a separate commit on main referencing the issue id.
        git(self.repo, "checkout", "bento-777-landed-elsewhere")
        self._commit("extra.txt", "e\n", "add extra unmerged work")
        git(self.repo, "checkout", "main")
        self._commit(
            "ref.txt", "r\n", "fix something for bento-777 separately"
        )

        scan = self._scan(
            "--correlate-branches",
            "--tracker", "none",
            "--issue-pattern", r"(bento-[0-9]+)",
        )
        rec = self._branch_record(scan, "bento-777-landed-elsewhere")
        self.assertEqual(rec["classification"], "review_required")
        corr = rec["correlation"]
        self.assertEqual(corr["issue_id"], "bento-777")
        self.assertEqual(corr["cherry_equivalent_count"], 1)
        self.assertEqual(corr["cherry_unique_count"], 1)
        # Both the cherry-pick (preserves original commit message) and the
        # explicit "fix... bento-777 separately" commit hit the grep.
        self.assertGreaterEqual(len(corr["main_commits_referencing_issue"]), 1)

    def test_correlate_off_by_default(self) -> None:
        git(self.repo, "checkout", "-b", "bento-111-feature")
        self._commit("f.txt", "f\n", "add f")
        git(self.repo, "checkout", "main")
        scan = self._scan()
        rec = self._branch_record(scan, "bento-111-feature")
        self.assertNotIn("correlation", rec)

    def test_correlate_no_issue_id_when_branch_does_not_match(self) -> None:
        git(self.repo, "checkout", "-b", "wip-no-tracker-id")
        self._commit("f.txt", "f\n", "add f")
        git(self.repo, "checkout", "main")
        scan = self._scan(
            "--correlate-branches",
            "--tracker", "none",
            "--issue-pattern", r"(bento-[0-9]+)",
        )
        rec = self._branch_record(scan, "wip-no-tracker-id")
        corr = rec["correlation"]
        self.assertIsNone(corr["issue_id"])
        self.assertEqual(corr["main_commits_referencing_issue"], [])


class CorrelationUnitTest(unittest.TestCase):
    """Direct tests on helper functions for tracker shim and signal extraction."""

    def setUp(self) -> None:
        self.mod = _load_module()

    def test_extract_issue_id_default_patterns(self) -> None:
        self.assertEqual(
            self.mod.extract_issue_id("bento-49l-foo", r"([a-z]+-[a-z0-9]+)"),
            "bento-49l",
        )
        self.assertEqual(
            self.mod.extract_issue_id("feat/PROJ-123-thing", r"([A-Z]+-[0-9]+)"),
            "PROJ-123",
        )
        self.assertIsNone(
            self.mod.extract_issue_id("just-words-here", r"([A-Z]+-[0-9]+)"),
        )

    def test_default_issue_pattern_per_tracker(self) -> None:
        self.assertEqual(self.mod.default_issue_pattern("beads"), r"([a-z]+-[a-z0-9]+)")
        self.assertEqual(self.mod.default_issue_pattern("jira"), r"([A-Z]+-[0-9]+)")
        self.assertIsNone(self.mod.default_issue_pattern("none"))

    def test_detect_tracker_prefers_beads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".beads").mkdir()
            self.assertEqual(self.mod.detect_tracker(root), "beads")

    def test_detect_tracker_jira_via_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = {
                "JIRA_BASE_URL": "https://example.atlassian.net",
                "JIRA_API_TOKEN": "x",
                "JIRA_USER_EMAIL": "u@e.com",
            }
            self.assertEqual(self.mod.detect_tracker(root, env=env), "jira")

    def test_detect_tracker_none_when_nothing_configured(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(
                self.mod.detect_tracker(Path(td), env={}, gh_available=False),
                "none",
            )


if __name__ == "__main__":
    unittest.main()
