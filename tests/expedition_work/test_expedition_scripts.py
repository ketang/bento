import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, write


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCRIPT = REPO_ROOT / "catalog/skills/expedition-work/scripts/expedition-bootstrap.py"
DISCOVER_SCRIPT = REPO_ROOT / "catalog/skills/expedition-work/scripts/expedition-discover.py"
START_SCRIPT = REPO_ROOT / "catalog/skills/expedition-work/scripts/expedition-start-task.py"
VERIFY_SCRIPT = REPO_ROOT / "catalog/skills/expedition-work/scripts/expedition-verify.py"
CLOSE_SCRIPT = REPO_ROOT / "catalog/skills/expedition-work/scripts/expedition-close-task.py"
FINISH_SCRIPT = REPO_ROOT / "catalog/skills/expedition-work/scripts/expedition-finish.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


class ExpeditionWorkScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Expedition Work Test")
        git(self.repo, "config", "user.email", "expedition-work@example.com")
        write(self.repo / "README.md", "root\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_bootstrap(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(BOOTSTRAP_SCRIPT), *args], cwd or self.repo, check=check)

    def run_discover(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(DISCOVER_SCRIPT), *args], cwd or self.repo, check=check)

    def run_start(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(START_SCRIPT), *args], cwd, check=check)

    def run_verify(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(VERIFY_SCRIPT), *args], cwd, check=check)

    def run_close(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(CLOSE_SCRIPT), *args], cwd, check=check)

    def run_finish(self, *args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(FINISH_SCRIPT), *args], cwd, check=check)

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
        self.assertIsNone(state["active_task"])
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
        self.assertEqual(state["active_task"]["branch"], "alpha-expedition-01-prepare-handoff")
        self.assertEqual(state["active_task"]["slug"], "prepare-handoff")
        self.assertEqual(state["active_task"]["kind"], "task")

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
        self.assertIsNone(state["active_task"])
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
        self.assertIsNone(state["active_task"])
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


if __name__ == "__main__":
    unittest.main()
