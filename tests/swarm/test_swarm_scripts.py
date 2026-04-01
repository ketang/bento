import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TRIAGE_SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-triage.py"
VERIFY_SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-worktree-verify.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


class SwarmTriageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_triage(self, payload: dict) -> dict:
        input_path = self.workspace / "triage.json"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        result = run(["python3", str(TRIAGE_SCRIPT), "--input", str(input_path)], self.workspace)
        return json.loads(result.stdout)

    def test_triage_uses_landed_task_ids_to_form_current_frontier(self) -> None:
        payload = {
            "tasks": [
                {"id": "task-a", "priority": 1, "paths": ["pkg/a"]},
                {"id": "task-b", "priority": 2, "paths": ["pkg/b"], "dependencies": ["task-a"]},
                {"id": "task-c", "priority": 3, "paths": ["pkg/c"], "dependencies": ["task-done"]},
            ],
            "landed_task_ids": ["task-done"],
            "max_parallel": 3,
            "batch_limit": 10,
        }

        output = self.run_triage(payload)

        self.assertEqual(output["parallel_batch"], ["task-a", "task-c"])
        self.assertEqual(
            output["deferred_due_to_dependencies"],
            [{"id": "task-b", "dependencies": ["task-a"]}],
        )

    def test_triage_reports_overlap_and_parallel_limit_separately(self) -> None:
        payload = {
            "tasks": [
                {"id": "task-a", "priority": 1, "paths": ["pkg/shared"]},
                {"id": "task-b", "priority": 2, "paths": ["pkg/shared"]},
                {"id": "task-c", "priority": 3, "paths": ["pkg/c"]},
            ],
            "max_parallel": 1,
            "batch_limit": 10,
        }

        output = self.run_triage(payload)

        self.assertEqual(output["parallel_batch"], ["task-a"])
        self.assertIn({"id": "task-b", "reason": "path_overlap_with_batch"}, output["wait_queue"])
        self.assertIn({"id": "task-c", "reason": "max_parallel_limit"}, output["wait_queue"])


class SwarmWorktreeVerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.worktree = Path(self.temp_dir.name) / "swarm-worktree"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Swarm Test")
        git(self.repo, "config", "user.email", "swarm@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        git(self.repo, "worktree", "add", "-b", "feature/swarm", str(self.worktree), "main")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_verify(self, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run(["python3", str(VERIFY_SCRIPT), *args], cwd, check=check)

    def test_verify_accepts_linked_worktree(self) -> None:
        result = self.run_verify(
            self.worktree,
            "--expected-branch",
            "feature/swarm",
            "--expected-worktree",
            str(self.worktree),
            "--require-linked-worktree",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["linked_worktree"])
        self.assertEqual(payload["branch"], "feature/swarm")

    def test_verify_rejects_primary_checkout_when_linked_worktree_is_required(self) -> None:
        result = self.run_verify(self.repo, "--require-linked-worktree", check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["linked_worktree"])


if __name__ == "__main__":
    unittest.main()
