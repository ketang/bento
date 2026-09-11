import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "bento"
    / "claude"
    / "scripts"
    / "require-worktree-git-guard.py"
)


class RequireWorktreeGitGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        )

    def _init_primary_repo(self, name: str = "repo") -> Path:
        repo = self.root / name
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.name", "Git Guard Test")
        self._git(repo, "config", "user.email", "git-guard@example.com")
        (repo / "README.md").write_text("test\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def _add_linked_worktree(self, repo: Path, branch: str = "feature/test") -> Path:
        worktree = self.root / "worktree"
        self._git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
        return worktree

    def run_hook(self, command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        payload = json.dumps({"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}})
        return subprocess.run(
            [str(HOOK_SCRIPT)], input=payload, cwd=cwd, capture_output=True, text=True, check=False,
        )

    # -- mutation rule: primary checkout only --------------------------------

    def test_denies_merge_in_primary_checkout(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("git merge feature", repo)
        self.assertEqual(result.returncode, 2)
        self.assertIn("git merge", result.stderr)

    def test_denies_rebase_reset_clean_in_primary_checkout(self) -> None:
        repo = self._init_primary_repo()
        for cmd in ("git rebase main", "git reset --hard HEAD~1", "git clean -fd"):
            with self.subTest(cmd=cmd):
                result = self.run_hook(cmd, repo)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_denies_checkout_of_primary_branch(self) -> None:
        repo = self._init_primary_repo()
        self._git(repo, "checkout", "-b", "other")
        result = self.run_hook("git checkout main", repo)
        self.assertEqual(result.returncode, 2)

    def test_allows_checkout_of_non_primary_branch(self) -> None:
        repo = self._init_primary_repo()
        self._git(repo, "branch", "other")
        result = self.run_hook("git checkout other", repo)
        self.assertEqual(result.returncode, 0)

    def test_denies_branch_delete_of_primary_branch(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("git branch -D main", repo)
        self.assertEqual(result.returncode, 2)

    def test_allows_branch_delete_of_non_primary_branch(self) -> None:
        repo = self._init_primary_repo()
        self._git(repo, "branch", "other")
        result = self.run_hook("git branch -D other", repo)
        self.assertEqual(result.returncode, 0)

    def test_denies_force_push(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("git push --force origin main", repo)
        self.assertEqual(result.returncode, 2)

    def test_allows_plain_push(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("git push origin main", repo)
        self.assertEqual(result.returncode, 0)

    def test_allows_non_mutating_git_commands(self) -> None:
        repo = self._init_primary_repo()
        for cmd in ("git status", "git log -1", "git diff", "git worktree list"):
            with self.subTest(cmd=cmd):
                result = self.run_hook(cmd, repo)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_mutation_in_a_linked_worktree(self) -> None:
        repo = self._init_primary_repo()
        worktree = self._add_linked_worktree(repo)
        result = self.run_hook("git merge main", worktree)
        self.assertEqual(result.returncode, 0)

    # -- land-work marker escape hatch ---------------------------------------

    def test_land_work_marker_bypasses_mutation_rule(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("BENTO_LAND_WORK=1 git merge feature", repo)
        self.assertEqual(result.returncode, 0)

    def test_land_work_marker_bypasses_no_verify_rule_too(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("BENTO_LAND_WORK=1 git commit --no-verify -m x", repo)
        self.assertEqual(result.returncode, 0)

    # -- require_worktree=false opt-out (shared with require-worktree.sh) ---

    def test_require_worktree_false_disables_mutation_rule(self) -> None:
        repo = self._init_primary_repo()
        (repo / ".agent-mode.local").write_text("require_worktree=false\n", encoding="utf-8")
        result = self.run_hook("git merge feature", repo)
        self.assertEqual(result.returncode, 0)

    def test_require_worktree_false_does_not_disable_no_verify_rule(self) -> None:
        repo = self._init_primary_repo()
        (repo / ".agent-mode.local").write_text("require_worktree=false\n", encoding="utf-8")
        result = self.run_hook("git commit --no-verify -m x", repo)
        self.assertEqual(result.returncode, 2)

    # -- hook-bypass rule: any checkout, not just primary --------------------

    def test_denies_no_verify_in_linked_worktree_too(self) -> None:
        repo = self._init_primary_repo()
        worktree = self._add_linked_worktree(repo)
        result = self.run_hook("git commit --no-verify -m x", worktree)
        self.assertEqual(result.returncode, 2)

    def test_denies_core_hooks_path_override(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("git -c core.hooksPath=/dev/null commit -m x", repo)
        self.assertEqual(result.returncode, 2)
        self.assertIn("core.hooksPath", result.stderr)

    def test_denies_core_hooks_path_override_long_flag(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("git --config core.hooksPath=/dev/null commit -m x", repo)
        self.assertEqual(result.returncode, 2)

    def test_hook_bypass_allow_disables_no_verify_rule(self) -> None:
        repo = self._init_primary_repo()
        (repo / ".agent-mode.local").write_text("hook_bypass=allow\n", encoding="utf-8")
        result = self.run_hook("git commit --no-verify -m x", repo)
        self.assertEqual(result.returncode, 0)

    def test_hook_bypass_allow_does_not_disable_mutation_rule(self) -> None:
        repo = self._init_primary_repo()
        (repo / ".agent-mode.local").write_text("hook_bypass=allow\n", encoding="utf-8")
        result = self.run_hook("git merge feature", repo)
        self.assertEqual(result.returncode, 2)

    # -- contract: never blocks unrelated tool calls or malformed input ------

    def test_non_bash_tool_is_ignored(self) -> None:
        repo = self._init_primary_repo()
        payload = json.dumps({"tool_name": "Write", "cwd": str(repo), "tool_input": {"file_path": "x"}})
        result = subprocess.run(
            [str(HOOK_SCRIPT)], input=payload, cwd=repo, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_non_git_command_is_ignored(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("ls -la", repo)
        self.assertEqual(result.returncode, 0)

    def test_malformed_stdin_exits_zero(self) -> None:
        result = subprocess.run(
            [str(HOOK_SCRIPT)], input="not json", capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_non_git_repo_cwd_is_ignored(self) -> None:
        non_repo = self.root / "plain"
        non_repo.mkdir()
        result = self.run_hook("git merge feature", non_repo)
        self.assertEqual(result.returncode, 0)

    def test_chained_command_with_git_mutation_is_still_caught(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("echo hi && git merge feature", repo)
        self.assertEqual(result.returncode, 2)

    def test_checkout_restoring_a_file_from_primary_branch_is_allowed(self) -> None:
        # Code review: 'git checkout main -- file.txt' restores a file from
        # the primary branch's tree; it does not switch the current branch,
        # and must not be blocked as a branch switch.
        repo = self._init_primary_repo()
        result = self.run_hook("git checkout main -- README.md", repo)
        self.assertEqual(result.returncode, 0)

    def test_commit_short_no_verify_flag_is_denied(self) -> None:
        # Code review: '-n' is the documented short alias for --no-verify on
        # git commit specifically.
        repo = self._init_primary_repo()
        result = self.run_hook("git commit -n -m x", repo)
        self.assertEqual(result.returncode, 2)

    def test_short_no_verify_flag_on_unrelated_subcommand_is_not_misread(self) -> None:
        # '-n' means something else entirely for other subcommands (e.g.
        # 'git log -n 5' limits output) and must not be misread as
        # --no-verify there.
        repo = self._init_primary_repo()
        result = self.run_hook("git log -n 5", repo)
        self.assertEqual(result.returncode, 0)

    def test_plus_refspec_force_push_is_denied(self) -> None:
        # Code review: 'git push origin +feature:main' force-pushes via the
        # leading '+' refspec marker, without any --force flag.
        repo = self._init_primary_repo()
        result = self.run_hook("git push origin +feature:main", repo)
        self.assertEqual(result.returncode, 2)

    def test_non_git_command_never_shells_out_to_git(self) -> None:
        # Code review: a non-git command must skip repo/git resolution
        # entirely (no subprocess git calls at all), not just skip the block
        # decision. Prove it with a fake `git` on PATH that leaves a marker
        # file if invoked, ahead of the real git in PATH.
        repo = self._init_primary_repo()
        marker = self.root / "git-was-called"
        fake_bin = self.root / "fakebin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        fake_git.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n", encoding="utf-8")
        fake_git.chmod(0o755)
        env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        payload = json.dumps({"tool_name": "Bash", "cwd": str(repo), "tool_input": {"command": "ls -la"}})
        subprocess.run([str(HOOK_SCRIPT)], input=payload, cwd=repo, capture_output=True, text=True, env=env)
        self.assertFalse(marker.exists(), "the guard shelled out to git for a non-git command")

    def test_git_merge_as_a_branch_name_substring_is_not_falsely_matched(self) -> None:
        # A branch literally named "merge-tool" must not trip the checkout
        # rule for the primary branch "main".
        repo = self._init_primary_repo()
        self._git(repo, "branch", "merge-tool")
        result = self.run_hook("git checkout merge-tool", repo)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
