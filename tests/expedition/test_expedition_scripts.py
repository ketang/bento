import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, write


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPEDITION_SCRIPT = REPO_ROOT / "catalog/skills/expedition/scripts/expedition.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


class ExpeditionWorkScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Expedition Work Test")
        git(self.repo, "config", "user.email", "expedition@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_bootstrap(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(EXPEDITION_SCRIPT), "bootstrap", *args], cwd or self.repo, check=check)

    def run_discover(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(EXPEDITION_SCRIPT), "discover", *args], cwd or self.repo, check=check)

    def run_start(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(EXPEDITION_SCRIPT), "start-task", *args], cwd, check=check)

    def run_verify(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(EXPEDITION_SCRIPT), "verify", *args], cwd, check=check)

    def run_close(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(EXPEDITION_SCRIPT), "close-task", *args], cwd, check=check)

    def run_finish(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(EXPEDITION_SCRIPT), "finish", *args], cwd, check=check)

    def bootstrap_expedition(self, expedition: str = "alpha-expedition") -> tuple[dict[str, object], Path]:
        worktree = Path(self.temp_dir.name) / expedition
        result = self.run_bootstrap(
            "--expedition",
            expedition,
            "--worktree",
            str(worktree),
            "--apply",
        )
        return json.loads(result.stdout), worktree

    def read_state(self, worktree: Path, expedition: str = "alpha-expedition") -> dict[str, object]:
        state_path = worktree / "docs" / "expeditions" / expedition / "state.json"
        return json.loads(state_path.read_text(encoding="utf-8"))

    def test_bootstrap_apply_creates_base_worktree_and_state_files(self) -> None:
        payload, worktree = self.bootstrap_expedition()

        self.assertTrue(payload["created"])
        self.assertEqual(payload["target_branch"], "alpha-expedition")
        self.assertTrue(worktree.exists())

        expedition_dir = worktree / "docs" / "expeditions" / "alpha-expedition"
        self.assertTrue((expedition_dir / "plan.md").exists())
        self.assertTrue((expedition_dir / "log.md").exists())
        self.assertTrue((expedition_dir / "handoff.md").exists())
        self.assertTrue((expedition_dir / "state.json").exists())

        state = self.read_state(worktree)
        self.assertEqual(state["base_branch"], "alpha-expedition")
        self.assertEqual(state["primary_branch"], "main")
        self.assertEqual(state["status"], "ready_for_task")
        self.assertEqual(state["active_branches"], [])
        self.assertEqual(state["next_task_number"], 1)

    def test_discover_lists_branch_local_expedition_state_from_linked_worktree(self) -> None:
        _, worktree = self.bootstrap_expedition()

        result = self.run_discover()
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["expeditions"]), 1)
        expedition = payload["expeditions"][0]
        self.assertEqual(expedition["expedition"], "alpha-expedition")
        self.assertEqual(expedition["base_worktree"], str(worktree.resolve()))
        self.assertTrue(expedition["handoff_file"].endswith("/docs/expeditions/alpha-expedition/handoff.md"))

    def test_start_task_apply_creates_meaningful_named_branch_and_updates_state(self) -> None:
        _, base_worktree = self.bootstrap_expedition()

        result = self.run_start(
            "--expedition",
            "alpha-expedition",
            "--slug",
            "prepare-handoff",
            "--apply",
            cwd=base_worktree,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["created"])
        self.assertEqual(payload["target_branch"], "alpha-expedition-01-prepare-handoff")
        self.assertTrue(Path(payload["target_worktree"]).exists())

        state = self.read_state(base_worktree)
        self.assertEqual(state["status"], "task_in_progress")
        active_head = state["active_branches"][0]
        self.assertEqual(active_head["branch"], "alpha-expedition-01-prepare-handoff")
        self.assertEqual(active_head["slug"], "prepare-handoff")
        self.assertEqual(active_head["kind"], "task")

    def test_verify_accepts_active_task_worktree(self) -> None:
        _, base_worktree = self.bootstrap_expedition()
        start = json.loads(
            self.run_start(
                "--expedition",
                "alpha-expedition",
                "--slug",
                "prepare-handoff",
                "--apply",
                cwd=base_worktree,
            ).stdout
        )
        task_worktree = Path(start["target_worktree"])

        result = self.run_verify("--expedition", "alpha-expedition", cwd=task_worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["current_role"], "active_task")
        self.assertEqual(payload["branch"], "alpha-expedition-01-prepare-handoff")

    def test_close_task_kept_merges_into_base_and_rebases_base_onto_main(self) -> None:
        _, base_worktree = self.bootstrap_expedition()
        start = json.loads(
            self.run_start(
                "--expedition",
                "alpha-expedition",
                "--slug",
                "prepare-handoff",
                "--apply",
                cwd=base_worktree,
            ).stdout
        )
        task_worktree = Path(start["target_worktree"])

        write(task_worktree / "task.txt", "kept\n")
        git(task_worktree, "add", "task.txt")
        git(task_worktree, "commit", "-m", "add kept task result")

        result = self.run_close(
            "--expedition",
            "alpha-expedition",
            "--outcome",
            "kept",
            "--summary",
            "Landed the first task",
            "--apply",
            cwd=base_worktree,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["updated"])
        self.assertTrue(payload["merged"])
        self.assertTrue(payload["rebased"])

        state = self.read_state(base_worktree)
        self.assertEqual(state["status"], "ready_for_task")
        self.assertEqual(state["active_branches"], [])
        self.assertEqual(state["next_task_number"], 2)
        self.assertEqual(state["last_completed"]["outcome"], "kept")
        self.assertEqual((base_worktree / "task.txt").read_text(encoding="utf-8"), "kept\n")

    def test_close_task_failed_experiment_preserves_branch_without_merging(self) -> None:
        _, base_worktree = self.bootstrap_expedition()
        self.run_start(
            "--expedition",
            "alpha-expedition",
            "--kind",
            "experiment",
            "--slug",
            "parser-probe",
            "--apply",
            cwd=base_worktree,
        )

        result = self.run_close(
            "--expedition",
            "alpha-expedition",
            "--outcome",
            "failed-experiment",
            "--summary",
            "The experiment regressed throughput",
            "--apply",
            cwd=base_worktree,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["updated"])
        self.assertFalse(payload["merged"])
        self.assertFalse(payload["rebased"])

        state = self.read_state(base_worktree)
        self.assertEqual(state["status"], "ready_for_task")
        self.assertEqual(state["active_branches"], [])
        self.assertEqual(state["next_task_number"], 2)
        self.assertEqual(len(state["preserved_experiments"]), 1)
        self.assertEqual(state["preserved_experiments"][0]["branch"], "alpha-expedition-exp-01-parser-probe")

    def test_finish_apply_removes_branch_local_expedition_docs_after_closeout(self) -> None:
        _, base_worktree = self.bootstrap_expedition()

        result = self.run_finish("--expedition", "alpha-expedition", "--apply", cwd=base_worktree)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["updated"])
        self.assertTrue(payload["docs_removed"])
        self.assertFalse((base_worktree / "docs" / "expeditions" / "alpha-expedition").exists())

    def test_bootstrap_initializes_active_branches_and_landing_lease(self) -> None:
        _, worktree = self.bootstrap_expedition()
        state = self.read_state(worktree)
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["active_branches"], [])
        self.assertIsNone(state["landing_lease"])

    def test_state_migration_from_schema_v1_active_task(self) -> None:
        from pathlib import Path as _P
        import json as _j
        _, worktree = self.bootstrap_expedition()
        state_file = worktree / "docs" / "expeditions" / "alpha-expedition" / "state.json"
        legacy = {
            "schema_version": 1,
            "expedition": "alpha-expedition",
            "primary_branch": "main",
            "base_branch": "alpha-expedition",
            "base_worktree": str(worktree.resolve()),
            "status": "task_in_progress",
            "next_task_number": 3,
            "active_task": {
                "number": 2,
                "kind": "task",
                "slug": "legacy-slug",
                "branch": "alpha-expedition-02-legacy-slug",
                "worktree": str((worktree.parent / "alpha-expedition-02-legacy-slug").resolve()),
                "base_head": "deadbeef",
                "started_at": "2026-04-01T00:00:00Z",
            },
            "last_completed": None,
            "preserved_experiments": [],
            "next_action": "",
            "created_at": "2026-04-01T00:00:00Z",
            "updated_at": "2026-04-01T00:00:00Z",
        }
        state_file.write_text(_j.dumps(legacy, indent=2) + "\n", encoding="utf-8")

        # A discover call triggers load_state through locate_expedition and should tolerate v1.
        result = self.run_discover()
        payload = _j.loads(result.stdout)
        self.assertTrue(payload["ok"])
        # active_task_branch is still reported via the existing discover contract.
        self.assertEqual(payload["expeditions"][0]["active_task_branch"], "alpha-expedition-02-legacy-slug")


    def test_start_task_allows_second_task_in_parallel(self) -> None:
        _, base_worktree = self.bootstrap_expedition()
        self.run_start(
            "--expedition", "alpha-expedition", "--slug", "first", "--apply",
            cwd=base_worktree,
        )
        result = self.run_start(
            "--expedition", "alpha-expedition", "--slug", "second", "--apply",
            cwd=base_worktree,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["created"])
        state = self.read_state(base_worktree)
        branches = [item["branch"] for item in state["active_branches"]]
        self.assertIn("alpha-expedition-01-first", branches)
        self.assertIn("alpha-expedition-02-second", branches)

    def test_start_task_rejects_second_perf_experiment(self) -> None:
        _, base_worktree = self.bootstrap_expedition()
        self.run_start(
            "--expedition", "alpha-expedition", "--kind", "perf-experiment",
            "--slug", "first-perf", "--apply",
            cwd=base_worktree,
        )
        result = self.run_start(
            "--expedition", "alpha-expedition", "--kind", "perf-experiment",
            "--slug", "second-perf", "--apply",
            cwd=base_worktree, check=False,
        )
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("perf-experiment" in err for err in payload["errors"]))

    def test_start_task_perf_experiment_does_not_block_regular_task(self) -> None:
        _, base_worktree = self.bootstrap_expedition()
        self.run_start(
            "--expedition", "alpha-expedition", "--kind", "perf-experiment",
            "--slug", "probe", "--apply",
            cwd=base_worktree,
        )
        result = self.run_start(
            "--expedition", "alpha-expedition", "--slug", "unrelated-task", "--apply",
            cwd=base_worktree,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["created"])

    def test_perf_experiment_branch_name_uses_perfexp_prefix(self) -> None:
        _, base_worktree = self.bootstrap_expedition()
        result = self.run_start(
            "--expedition", "alpha-expedition", "--kind", "perf-experiment",
            "--slug", "probe-a", "--apply",
            cwd=base_worktree,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["target_branch"], "alpha-expedition-perfexp-01-probe-a")
        self.assertEqual(payload["kind"], "perf-experiment")

    def test_close_task_rebases_task_branch_onto_current_base_tip(self) -> None:
        # Launch two parallel tasks, advance base via closing the first,
        # then close the second and verify it was rebased onto the advanced base.
        _, base_worktree = self.bootstrap_expedition()

        start_a = json.loads(
            self.run_start(
                "--expedition", "alpha-expedition", "--slug", "task-a", "--apply",
                cwd=base_worktree,
            ).stdout
        )
        start_b = json.loads(
            self.run_start(
                "--expedition", "alpha-expedition", "--slug", "task-b", "--apply",
                cwd=base_worktree,
            ).stdout
        )
        a_worktree = Path(start_a["target_worktree"])
        b_worktree = Path(start_b["target_worktree"])

        write(a_worktree / "a.txt", "a\n")
        git(a_worktree, "add", "a.txt")
        git(a_worktree, "commit", "-m", "add a")

        write(b_worktree / "b.txt", "b\n")
        git(b_worktree, "add", "b.txt")
        git(b_worktree, "commit", "-m", "add b")

        self.run_close(
            "--expedition", "alpha-expedition", "--branch", start_a["target_branch"],
            "--outcome", "kept", "--summary", "A", "--apply",
            cwd=base_worktree,
        )
        self.run_close(
            "--expedition", "alpha-expedition", "--branch", start_b["target_branch"],
            "--outcome", "kept", "--summary", "B", "--apply",
            cwd=base_worktree,
        )

        # After both land, both files exist on base.
        self.assertTrue((base_worktree / "a.txt").exists())
        self.assertTrue((base_worktree / "b.txt").exists())

    def test_close_task_lease_is_recorded_and_released(self) -> None:
        _, base_worktree = self.bootstrap_expedition()
        start = json.loads(
            self.run_start(
                "--expedition", "alpha-expedition", "--slug", "only", "--apply",
                cwd=base_worktree,
            ).stdout
        )
        task_worktree = Path(start["target_worktree"])
        write(task_worktree / "task.txt", "kept\n")
        git(task_worktree, "add", "task.txt")
        git(task_worktree, "commit", "-m", "add kept task result")

        self.run_close(
            "--expedition", "alpha-expedition", "--outcome", "kept",
            "--summary", "done", "--apply",
            cwd=base_worktree,
        )
        state = self.read_state(base_worktree)
        self.assertIsNone(state["landing_lease"])


    def test_discover_reports_stale_active_branch_when_worktree_missing(self) -> None:
        import shutil as _shutil
        _, base_worktree = self.bootstrap_expedition()
        start = json.loads(
            self.run_start(
                "--expedition", "alpha-expedition", "--slug", "will-go-stale", "--apply",
                cwd=base_worktree,
            ).stdout
        )
        task_worktree = Path(start["target_worktree"])
        _shutil.rmtree(task_worktree)

        result = self.run_discover()
        payload = json.loads(result.stdout)
        expedition = payload["expeditions"][0]
        stale = expedition["stale_active_branches"]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["branch"], start["target_branch"])


if __name__ == "__main__":
    unittest.main()
