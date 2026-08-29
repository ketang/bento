import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git, run


REPO_ROOT = Path(__file__).resolve().parents[2]
TRIAGE_SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-triage.py"
VERIFY_SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-worktree-verify.py"


class SwarmTriageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_triage(self, payload: dict) -> dict:
        input_path = self.workspace / "triage.json"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        result = run([str(TRIAGE_SCRIPT), "--input", str(input_path)], self.workspace)
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

        self.other_worktree = Path(self.temp_dir.name) / "other-worktree"
        git(self.repo, "worktree", "add", "-b", "feature/other-task", str(self.other_worktree), "main")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_verify(self, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(VERIFY_SCRIPT), *args], cwd, check=check)

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

    def test_require_linked_worktree_from_primary_checkout_does_not_warn(self) -> None:
        # The warning is about identity ambiguity between linked worktrees; it
        # would be misleading ("you are in SOME linked worktree") when the
        # hard failure above already covers "you are not in one at all".
        result = self.run_verify(self.repo, "--require-linked-worktree", check=False)

        self.assertNotIn("warning:", result.stderr)

    def test_expected_branch_empty_string_is_rejected(self) -> None:
        result = self.run_verify(
            self.worktree,
            "--expected-branch",
            "",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--expected-branch requires a non-empty value", result.stderr)

    def test_expected_worktree_empty_string_is_rejected(self) -> None:
        # An unset shell variable interpolated into the invocation (e.g.
        # `--expected-worktree "$SOME_UNSET_VAR"`) must fail loudly instead of
        # silently coercing to "no expectation" and trivially passing.
        result = self.run_verify(
            self.worktree,
            "--expected-worktree",
            "",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--expected-worktree requires a non-empty value", result.stderr)

    def test_require_worktree_alias_warning_mentions_both_flag_names(self) -> None:
        result = self.run_verify(self.other_worktree, "--require-worktree")

        self.assertIn("--require-linked-worktree", result.stderr)
        self.assertIn("--require-worktree", result.stderr)

    def test_require_linked_worktree_alone_wrongly_passes_from_wrong_worktree(self) -> None:
        # This is the bug: a teammate assigned to `feature/swarm` who is
        # actually sitting in `feature/other-task` still gets ok:true because
        # --require-linked-worktree only checks "some linked worktree", not
        # "the assigned one".
        result = self.run_verify(self.other_worktree, "--require-linked-worktree")
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["branch"], "feature/other-task")

    def test_require_linked_worktree_alone_warns_without_expected_branch(self) -> None:
        result = self.run_verify(self.other_worktree, "--require-linked-worktree")

        self.assertIn("only checks that you are in", result.stderr)
        self.assertIn("--expected-branch", result.stderr)

    def test_expected_branch_suppresses_warning(self) -> None:
        result = self.run_verify(
            self.worktree,
            "--expected-branch",
            "feature/swarm",
            "--require-linked-worktree",
        )

        self.assertEqual(result.stderr, "")

    def test_expected_branch_rejects_wrong_linked_worktree(self) -> None:
        result = self.run_verify(
            self.other_worktree,
            "--expected-branch",
            "feature/swarm",
            "--require-linked-worktree",
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["expected_branch_match"])
        self.assertEqual(payload["branch"], "feature/other-task")

    def test_expected_branch_accepts_correct_linked_worktree(self) -> None:
        result = self.run_verify(
            self.worktree,
            "--expected-branch",
            "feature/swarm",
            "--require-linked-worktree",
        )
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["expected_branch_match"])


if __name__ == "__main__":
    unittest.main()
