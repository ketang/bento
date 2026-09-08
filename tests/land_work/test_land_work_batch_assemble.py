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
ASSEMBLE_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-batch-assemble.py"


def load_assemble_module():
    """Import land-work-batch-assemble.py directly (hyphenated filename, so
    not a normal import) to unit-test main() with mocked git_state helpers,
    for races that are impractical to reproduce via real concurrency.

    See load_script_module_with_git_state() for why the git_state.py swap is
    necessary.
    """
    return load_script_module_with_git_state("land_work_batch_assemble", ASSEMBLE_SCRIPT)


class LandWorkBatchAssembleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.integration = Path(self.temp_dir.name) / "integration"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Batch Assemble Test")
        git(self.repo, "config", "user.email", "batch-assemble@example.com")
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

    def run_assemble(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run([str(ASSEMBLE_SCRIPT), *args], self.repo, check=check)

    def test_assembles_all_non_conflicting_branches_in_order(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")
        self._make_branch("branch-b", "b.txt", "b\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "branch-b",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual([entry["branch"] for entry in payload["assembled"]], ["branch-a", "branch-b"])
        self.assertEqual(payload["evicted"], [])
        self.assertEqual((self.integration / "a.txt").read_text(encoding="utf-8"), "a\n")
        self.assertEqual((self.integration / "b.txt").read_text(encoding="utf-8"), "b\n")
        self.assertNotEqual(payload["tip_sha"], self.base_sha)

    def test_conflicting_branch_is_evicted_and_others_still_land(self) -> None:
        self._make_branch("branch-a", "shared.txt", "from a\n")
        self._make_branch("branch-b", "shared.txt", "from b\n")
        self._make_branch("branch-c", "c.txt", "c\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "branch-b",
            "--branch", "branch-c",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual([entry["branch"] for entry in payload["assembled"]], ["branch-a", "branch-c"])
        self.assertEqual(len(payload["evicted"]), 1)
        self.assertEqual(payload["evicted"][0]["branch"], "branch-b")
        self.assertIn("shared.txt", payload["evicted"][0]["conflicting_paths"])
        self.assertEqual((self.integration / "shared.txt").read_text(encoding="utf-8"), "from a\n")
        self.assertEqual((self.integration / "c.txt").read_text(encoding="utf-8"), "c\n")

    def test_worktree_left_clean_after_eviction(self) -> None:
        self._make_branch("branch-a", "shared.txt", "from a\n")
        self._make_branch("branch-b", "shared.txt", "from b\n")

        self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "branch-b",
        )

        status = git(self.integration, "status", "--porcelain=v1", "--untracked-files=all").stdout
        self.assertEqual(status.strip(), "")
        # A worktree's own .git is a file pointing at the admin dir; resolve it.
        git_dir = Path(git(self.integration, "rev-parse", "--git-dir").stdout.strip())
        if not git_dir.is_absolute():
            git_dir = self.integration / git_dir
        self.assertFalse((git_dir / "MERGE_HEAD").exists())

    def test_no_branches_leaves_tip_at_base(self) -> None:
        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["assembled"], [])
        self.assertEqual(payload["evicted"], [])
        self.assertEqual(payload["tip_sha"], self.base_sha)

    def test_nonexistent_branch_is_evicted_with_reason(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "does-not-exist",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual([entry["branch"] for entry in payload["assembled"]], ["branch-a"])
        self.assertEqual(len(payload["evicted"]), 1)
        self.assertEqual(payload["evicted"][0]["branch"], "does-not-exist")
        self.assertIn("does not exist", payload["evicted"][0]["reason"])

    def test_resets_worktree_to_base_ref_before_assembling(self) -> None:
        # A worktree left mid-merge or advanced from a prior batch attempt
        # must not leak into the next assemble call.
        self._make_branch("stale", "stale.txt", "stale\n")
        git(self.integration, "merge", "--no-ff", "stale")
        self._make_branch("branch-a", "a.txt", "a\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertFalse((self.integration / "stale.txt").exists())
        self.assertEqual((self.integration / "a.txt").read_text(encoding="utf-8"), "a\n")

    def test_refuses_to_reset_over_foreign_untracked_files(self) -> None:
        # Regression: SKILL.md documents that the worktree is validated
        # "exactly as land-work-create-preview.py does for a single
        # landing" — foreign, non-ignored untracked content means a person
        # or another tool touched the shared worktree and must not be
        # silently reset over.
        self._make_branch("branch-a", "a.txt", "a\n")
        (self.integration / "real-work.txt").write_text("not reproducible\n", encoding="utf-8")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("untracked files", payload["errors"][0])
        self.assertEqual(
            (self.integration / "real-work.txt").read_text(encoding="utf-8"), "not reproducible\n"
        )

    def test_rejects_worktree_not_registered_to_this_repo(self) -> None:
        unrelated = Path(self.temp_dir.name) / "unrelated"
        unrelated.mkdir()
        git(unrelated, "init", "-b", "main")

        result = self.run_assemble(
            "--worktree", str(unrelated),
            "--base-ref", self.base_sha,
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("not a registered git worktree", payload["errors"][0])

    def test_base_ref_that_stops_resolving_before_reset_is_a_structured_error(self) -> None:
        # Regression: rev_exists(base_ref) and rev_parse(base_ref) are two
        # separate git calls. If base_ref (a branch, not a bare SHA) stops
        # resolving between them (concurrent lease refresh, branch cleanup
        # sweep, another swarm agent), rev_parse must not crash main() with
        # an unhandled CalledProcessError -- it must degrade to the same
        # {ok: false, errors: [...]} JSON contract every other failure path
        # here maintains. The race itself is impractical to reproduce via
        # real concurrency in a deterministic test, so mock rev_parse to
        # simulate the second call losing the race.
        module = load_assemble_module()
        argv = [
            str(ASSEMBLE_SCRIPT),
            "--worktree", str(self.integration),
            "--base-ref", "main",
            "--branch", "does-not-matter",
        ]
        stdout = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", argv), unittest.mock.patch.object(
            module,
            "rev_parse",
            side_effect=subprocess.CalledProcessError(128, ["git", "rev-parse", "main"], stderr="unknown revision"),
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
        self.assertIn("main", payload["errors"][0])

    def test_reset_hard_failure_is_a_structured_error_not_a_crash(self) -> None:
        # Regression: `git reset --hard` was unguarded, unlike
        # land-work-create-preview.py's equivalent reset. A filesystem
        # hiccup or corrupted worktree must produce the JSON error contract,
        # not a raw traceback. A real failure is simulated by mocking the
        # module's own `git` call rather than chmod-ing the git-admin dir
        # read-only: chmod is a no-op for a root-run test process (root
        # bypasses file-mode permission checks), which would make this test
        # silently stop exercising the guarded path under a root-run
        # test/CI container.
        self._make_branch("branch-a", "a.txt", "a\n")
        module = load_assemble_module()
        original_git = module.git

        def guarded_git(*args, **kwargs):
            if args[:2] == ("reset", "--hard"):
                raise subprocess.CalledProcessError(128, ["git", *args], stderr="fatal: simulated reset failure")
            return original_git(*args, **kwargs)

        argv = [
            str(ASSEMBLE_SCRIPT),
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
        ]
        stdout = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", argv), unittest.mock.patch.object(
            module, "git", new=guarded_git
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
        self.assertTrue(payload["errors"])
        self.assertIn("reset --hard", payload["errors"][0])
        self.assertEqual(payload["base_sha"], self.base_sha)

    def test_corrupted_registered_worktree_is_a_structured_error_not_a_crash(self) -> None:
        # Regression: foreign_untracked_files()/registered_worktree_paths()
        # dropped land-work-create-preview.py's try/except around `git
        # worktree list` and `git status`, so a registered-but-corrupted
        # worktree (its own .git pointer file removed) crashed main() instead
        # of reporting the "git status failed" case create-preview.py
        # handles gracefully.
        self._make_branch("branch-a", "a.txt", "a\n")
        (self.integration / ".git").unlink()

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            check=False,
        )
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("git status", payload["errors"][0])

    def test_duplicate_branch_is_evicted_not_recorded_with_a_fabricated_merge_sha(self) -> None:
        # Regression: a --branch that resolves to a commit already an
        # ancestor of HEAD (duplicate branch in the queue, or transitively
        # already-contained via an earlier branch's history) makes `git
        # merge --no-ff` exit 0 with no new commit ("Already up to date.").
        # The old code recorded it as assembled with merge_commit_sha=HEAD,
        # colliding with whichever branch's merge actually produced that
        # commit.
        self._make_branch("branch-a", "a.txt", "a\n")

        result = self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "branch-a",
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["assembled"]), 1)
        self.assertEqual(payload["assembled"][0]["branch"], "branch-a")
        self.assertEqual(len(payload["evicted"]), 1)
        self.assertEqual(payload["evicted"][0]["branch"], "branch-a")
        self.assertIn("already up to date", payload["evicted"][0]["reason"])
        merge_shas = [entry["merge_commit_sha"] for entry in payload["assembled"]]
        self.assertEqual(len(merge_shas), len(set(merge_shas)))

    def test_worktree_becoming_unusable_mid_batch_is_a_structured_error_not_a_crash(self) -> None:
        # Regression: the per-branch merge loop's own git_stdout calls (the
        # post-merge HEAD lookup used for both merge_commit_sha and the
        # no-op-merge check) were unguarded even after the pre-loop setup
        # calls were hardened. The shared worktree can become unusable
        # between two of this script's own calls (another swarm agent, a
        # concurrent cleanup sweep) -- that must degrade to the JSON error
        # contract, with whatever was already assembled reported for
        # diagnosis, not an unhandled traceback.
        self._make_branch("branch-a", "a.txt", "a\n")
        self._make_branch("branch-b", "b.txt", "b\n")
        module = load_assemble_module()
        original_try_git_stdout = module.try_git_stdout
        calls_after_merge = {"count": 0}

        def guarded_try_git_stdout(*args, **kwargs):
            if args[:2] == ("rev-parse", "HEAD"):
                calls_after_merge["count"] += 1
                if calls_after_merge["count"] == 1:
                    # Let the first (post-branch-a-merge) lookup succeed so
                    # branch-a lands, then fail the next one.
                    return original_try_git_stdout(*args, **kwargs)
                return None
            return original_try_git_stdout(*args, **kwargs)

        argv = [
            str(ASSEMBLE_SCRIPT),
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
            "--branch", "branch-b",
        ]
        stdout = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", argv), unittest.mock.patch.object(
            module, "try_git_stdout", new=guarded_try_git_stdout
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
        self.assertTrue(payload["errors"])
        self.assertEqual([entry["branch"] for entry in payload["assembled"]], ["branch-a"])
        self.assertIsNone(payload["tip_sha"])

    def test_merge_commit_message_references_branch(self) -> None:
        self._make_branch("branch-a", "a.txt", "a\n")

        self.run_assemble(
            "--worktree", str(self.integration),
            "--base-ref", self.base_sha,
            "--branch", "branch-a",
        )

        subject = git(self.integration, "log", "-1", "--format=%s").stdout.strip()
        self.assertIn("branch-a", subject)


if __name__ == "__main__":
    unittest.main()
