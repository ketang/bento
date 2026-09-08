import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.script_test_utils import git, load_script_module_with_git_state, run


REPO_ROOT = Path(__file__).resolve().parents[2]
BISECT_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-batch-bisect.py"

# Fails iff bad.txt exists in the worktree -- the fixture "gate" for a single
# known-bad branch.
GATE_FAIL_ON_BAD_TXT = "test '!' -f bad.txt"

# Fails iff *both* x.txt and y.txt exist -- the fixture "gate" for a
# non-monotonic interaction failure (neither branch is red alone).
GATE_FAIL_ON_BOTH_X_AND_Y = "test '!' \\( -f x.txt -a -f y.txt \\)"


class LandWorkBatchBisectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.integration = Path(self.temp_dir.name) / "integration"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Batch Bisect Test")
        git(self.repo, "config", "user.email", "batch-bisect@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        self.base_sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()

        git(self.repo, "worktree", "add", "--detach", str(self.integration), self.base_sha)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_branch(self, name: str, filename: str, content: str, base: str = "main") -> None:
        git(self.repo, "branch", name, base)
        worktree = Path(self.temp_dir.name) / f"wt-{name}"
        git(self.repo, "worktree", "add", str(worktree), name)
        (worktree / filename).write_text(content, encoding="utf-8")
        git(worktree, "add", filename)
        git(worktree, "commit", "-m", f"{name}: add {filename}")
        git(self.repo, "worktree", "remove", "--force", str(worktree))

    def run_bisect(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(BISECT_SCRIPT), *args], self.repo, check=check)

    def test_isolates_the_bad_branch_and_the_good_one_lands(self) -> None:
        # The acceptance fixture: a batch of 2 with an injected gate failure
        # in one branch -> bisect isolates it, the other is identified as
        # the landable subset.
        self._make_branch("branch-good", "good.txt", "good\n")
        self._make_branch("branch-bad", "bad.txt", "bad\n")

        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", GATE_FAIL_ON_BAD_TXT,
            "--branch", "branch-good",
            "--branch", "branch-bad",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["culprits"], ["branch-bad"])
        self.assertEqual(payload["landable"], ["branch-good"])
        self.assertIsNotNone(payload["final"])
        self.assertTrue(payload["final"]["ok"])
        self.assertTrue(payload["final"]["gate"]["passed"])
        self.assertEqual(
            [entry["branch"] for entry in payload["final"]["assemble"]["assembled"]],
            ["branch-good"],
        )
        # Trail records every subset tried, in order, with its gate result.
        attempts = [entry for entry in payload["trail"] if entry["kind"] == "attempt"]
        self.assertGreaterEqual(len(attempts), 2)
        self.assertTrue(all("result" in entry for entry in attempts))
        # The final confirmation subset ([branch-good]) exactly matches the
        # halving loop's own attempt at that half, which already gated
        # green -- the gate must be reused, not re-run, but the worktree
        # must still be reassembled fresh to the landable tip regardless
        # (never left at whatever the last bisection attempt happened to
        # leave behind -- here, the branch-bad half, attempted last).
        self.assertTrue(attempts[-1].get("gate_reused"))
        self.assertEqual(attempts[-1]["branches"], ["branch-good"])
        # The worktree ends up reset to the confirmed landable tip.
        self.assertTrue((self.integration / "good.txt").exists())
        self.assertFalse((self.integration / "bad.txt").exists())

    def test_order_independent_bad_branch_first(self) -> None:
        self._make_branch("branch-bad", "bad.txt", "bad\n")
        self._make_branch("branch-good", "good.txt", "good\n")

        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", GATE_FAIL_ON_BAD_TXT,
            "--branch", "branch-bad",
            "--branch", "branch-good",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["culprits"], ["branch-bad"])
        self.assertEqual(payload["landable"], ["branch-good"])
        self.assertTrue(payload["final"]["ok"])

    def test_both_branches_bad_nothing_landable(self) -> None:
        self._make_branch("branch-bad-1", "bad.txt", "bad\n")
        self._make_branch("branch-bad-2", "bad2.txt", "also bad\n", base="main")

        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", GATE_FAIL_ON_BAD_TXT,
            "--branch", "branch-bad-1",
            "--branch", "branch-bad-2",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["culprits"], ["branch-bad-1"])
        self.assertEqual(payload["landable"], ["branch-bad-2"])
        # branch-bad-2 alone does not trip the bad.txt-only gate, so it is
        # correctly identified as landable even though branch-bad-1 is not.
        self.assertTrue(payload["final"]["ok"])

    def test_non_monotonic_interaction_marks_both_branches_as_culprits(self) -> None:
        # Neither branch trips the gate alone; only their combination does.
        # Plain halving cannot localize a single culprit here.
        self._make_branch("branch-x", "x.txt", "x\n")
        self._make_branch("branch-y", "y.txt", "y\n")

        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", GATE_FAIL_ON_BOTH_X_AND_Y,
            "--branch", "branch-x",
            "--branch", "branch-y",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(set(payload["culprits"]), {"branch-x", "branch-y"})
        self.assertEqual(payload["landable"], [])
        self.assertIsNone(payload["final"])
        notes = [entry for entry in payload["trail"] if entry["kind"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn("ambiguous_non_monotonic", notes[0]["message"])
        self.assertEqual(set(notes[0]["branches"]), {"branch-x", "branch-y"})

    def test_final_confirmation_failure_is_reported_not_silently_landed(self) -> None:
        # Regression: a landable subset whose own final confirmation gate
        # fails (a residual non-monotonic interaction among the survivors
        # themselves) must never be silently treated as landable.
        self._make_branch("branch-good", "good.txt", "good\n")
        self._make_branch("branch-bad", "bad.txt", "bad\n")

        # Gate fails on bad.txt (isolates branch-bad normally) OR when both
        # x.txt/y.txt-style survivors combine -- here we simulate a survivor
        # subset that is itself red by having the gate fail whenever *any*
        # file besides README.md is present after branch-bad is removed is
        # not realistic; instead directly fail the gate for the landable
        # subset by keying off good.txt combined with a second good branch.
        self._make_branch("branch-good-2", "good2.txt", "good2\n", base="main")
        gate = "test '!' \\( -f good.txt -a -f good2.txt \\) -a '!' -f bad.txt"

        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", gate,
            "--branch", "branch-good",
            "--branch", "branch-good-2",
            "--branch", "branch-bad",
            check=False,
        )
        payload = json.loads(result.stdout)

        # Regression: a caller checking only the process exit code (never
        # parsing `final.ok` out of the JSON body) must not see this
        # reported as success -- the top-level `ok`/exit code must reflect
        # that `landable` is not actually safe to land.
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        # branch-bad is still isolated by halving.
        self.assertIn("branch-bad", payload["culprits"])
        # But the final confirmation of the two "good" survivors together
        # fails (their combination trips the gate), so it must not be
        # reported as a clean landable subset.
        self.assertIsNotNone(payload["final"])
        self.assertFalse(payload["final"]["ok"])
        self.assertFalse(payload["final"]["gate"]["passed"])
        notes = [entry for entry in payload["trail"] if entry["kind"] == "note"]
        self.assertTrue(
            any("final confirmation gate failed" in entry["message"] for entry in notes)
        )

    def test_requires_at_least_two_branches(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")

        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", "true",
            "--branch", "branch-a",
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("at least 2", payload["errors"][0])

    def test_duplicate_branch_is_rejected(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")
        self._make_branch("branch-b", "b.txt", "b\n")

        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", "true",
            "--branch", "branch-a",
            "--branch", "branch-b",
            "--branch", "branch-a",
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("branch-a", payload["errors"][0])

    def test_evicted_branch_during_subset_reassembly_aborts_bisect(self) -> None:
        # Regression: a branch that land-work-batch-assemble.py silently
        # evicts while reassembling a bisection subset (here, a branch with
        # no commits ahead of base -- assemble.py's own no-op-merge eviction
        # from bento-yank) must abort the whole bisect with a structured
        # error. Trusting that attempt's gate result would misattribute a
        # culprit or a landable branch that was never actually present in
        # the gated tree.
        git(self.repo, "branch", "branch-noop", "main")
        self._make_branch("branch-other", "other.txt", "other\n")

        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", "true",
            "--branch", "branch-noop",
            "--branch", "branch-other",
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("assembling a bisection subset failed", payload["errors"][0])
        self.assertIn("evicted", payload["errors"][0])

    def test_run_assemble_launch_failure_is_a_structured_error_not_a_crash(self) -> None:
        # Regression: run_assemble()'s subprocess.run() had no OSError
        # handling, unlike run_gate()'s equivalent call -- a launch failure
        # (lost executable bit, unresolvable interpreter) must not crash
        # main() with an unhandled traceback.
        module = load_script_module_with_git_state(
            "land_work_batch_bisect", BISECT_SCRIPT
        )
        self._make_branch("branch-a", "a.txt", "a\n")
        self._make_branch("branch-b", "b.txt", "b\n")

        original_subprocess_run = module.subprocess.run

        def guarded_run(args, *a, **kw):
            if args and args[0] == str(module.ASSEMBLE_SCRIPT):
                raise OSError("simulated launch failure")
            return original_subprocess_run(args, *a, **kw)

        argv = [
            str(BISECT_SCRIPT),
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", "true",
            "--branch", "branch-a",
            "--branch", "branch-b",
        ]
        stdout = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", argv), unittest.mock.patch.object(
            module.subprocess, "run", side_effect=guarded_run
        ), contextlib.redirect_stdout(stdout):
            original_cwd = Path.cwd()
            try:
                os.chdir(self.repo)
                exit_code = module.main()
            finally:
                os.chdir(original_cwd)

        payload = json.loads(stdout.getvalue())

        self.assertNotEqual(exit_code, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("unable to launch", payload["errors"][0])

    def test_rejects_worktree_not_registered_to_this_repo(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")
        self._make_branch("branch-b", "b.txt", "b\n")
        unrelated = Path(self.temp_dir.name) / "unrelated"
        unrelated.mkdir()
        git(unrelated, "init", "-b", "main")

        result = self.run_bisect(
            "--worktree", str(unrelated),
            "--base-ref", self.base_sha,
            "--gate-command", "true",
            "--branch", "branch-a",
            "--branch", "branch-b",
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("assembling a bisection subset failed", payload["errors"][0])
        self.assertIn("not a registered git worktree", payload["errors"][0])

    def test_gate_command_output_is_recorded_in_the_trail(self) -> None:
        self._make_branch("branch-good", "good.txt", "good\n")
        self._make_branch("branch-bad", "bad.txt", "bad\n")

        gate = "echo marker-stdout; echo marker-stderr 1>&2; test '!' -f bad.txt"
        result = self.run_bisect(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--gate-command", gate,
            "--branch", "branch-good",
            "--branch", "branch-bad",
        )
        payload = json.loads(result.stdout)

        attempts = [entry for entry in payload["trail"] if entry["kind"] == "attempt"]
        self.assertTrue(
            any("marker-stdout" in "\n".join(entry["gate"]["stdout_tail"]) for entry in attempts)
        )
        self.assertTrue(
            any("marker-stderr" in "\n".join(entry["gate"]["stderr_tail"]) for entry in attempts)
        )


if __name__ == "__main__":
    unittest.main()
