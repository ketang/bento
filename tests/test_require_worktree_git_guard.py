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
CORPUS_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "shell_segments_corpus.json"


def _corpus_command(row_number: int) -> str:
    rows = json.loads(CORPUS_FIXTURE.read_text(encoding="utf-8"))
    return rows[row_number - 1]["command"]


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

    def test_allows_push_to_non_primary_branch(self) -> None:
        repo = self._init_primary_repo()
        self._git(repo, "checkout", "-q", "-b", "other")
        for cmd in ("git push origin other", "git push origin HEAD:other", "git push"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, repo).returncode, 0)

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

    # -- effective repo: git -C and leading cd (bento-c96u.1, bento-c9c5) ----

    def _pair(self) -> tuple[Path, Path]:
        repo = self._init_primary_repo()
        return repo, self._add_linked_worktree(repo)

    def test_git_dash_c_primary_from_worktree_is_denied(self) -> None:
        repo, wt = self._pair()
        for cmd in (
            f"git -C {repo} merge --no-ff feature/test",
            f"git -C {repo} reset --hard HEAD~1",
            f"cd {repo} && git merge --ff-only feature/test",
            f"git -C {wt} status && git -C {repo} reset --hard",
            f"git -C {repo}/. merge x",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, wt).returncode, 2)

    def test_git_dash_c_worktree_from_primary_is_allowed(self) -> None:
        repo, wt = self._pair()
        for cmd in (
            f"git -C {wt} rebase main",
            f"cd {wt} && git rebase main",
            f"git -C {wt} status",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, repo).returncode, 0)

    def test_git_dash_c_relative_and_chained(self) -> None:
        repo, wt = self._pair()
        rel_wt = os.path.relpath(wt, repo)
        self.assertEqual(self.run_hook(f"git -C {rel_wt} rebase main", repo).returncode, 0)
        rel_repo = os.path.relpath(repo, wt)
        self.assertEqual(self.run_hook(f"git -C {rel_repo} merge x", wt).returncode, 2)
        # -C a -C b composes: b is resolved against a.
        self.assertEqual(
            self.run_hook(f"git -C {wt.parent} -C {repo.name} merge x", wt).returncode, 2,
        )
        self.assertEqual(
            self.run_hook(f"git -C {wt.parent} -C {wt.name} merge x", repo).returncode, 0,
        )

    def test_cd_relative_resolves_against_running_dir(self) -> None:
        repo, wt = self._pair()
        self.assertEqual(
            self.run_hook(f"cd {os.path.relpath(repo, wt)} && git merge x", wt).returncode, 2,
        )

    def test_unresolvable_target_fails_closed_for_mutations(self) -> None:
        repo, wt = self._pair()
        for cmd in (
            'cd "$X" && git merge y',
            'git -C "$X" merge y',
            'cd $(pwd) && git reset --hard',
            'cd - && git merge y',
            'cd "$X" && git push origin HEAD:main',
        ):
            for cwd in (repo, wt):
                with self.subTest(cmd=cmd, cwd=cwd.name):
                    self.assertEqual(self.run_hook(cmd, cwd).returncode, 2)
        for cmd in ('cd "$X" && git status', 'git -C "$X" log -1', 'cd "$X" && git push origin feat'):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, wt).returncode, 0)

    def test_cd_flags_are_parsed(self) -> None:
        repo, wt = self._pair()
        for cmd in (f"cd -P {repo} && git merge x", f"cd -- {repo} && git merge x"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, wt).returncode, 2)
        self.assertEqual(self.run_hook(f"cd -P {wt} && git rebase main", repo).returncode, 0)

    def test_payload_cwd_outside_any_repo_still_checks_effective_repo(self) -> None:
        repo, wt = self._pair()
        outside = self.root / "outside"
        outside.mkdir()
        for cmd in (
            f"git -C {repo} merge x",
            f"cd {repo} && git merge x",
            f"cd {repo} && git push origin main",
            f"git -C {repo} push origin HEAD:main",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, outside).returncode, 2)
        self.assertEqual(self.run_hook(f"git -C {wt} rebase main", outside).returncode, 0)
        self.assertEqual(self.run_hook("git merge x", outside).returncode, 0)

    def test_dash_c_nonexistent_falls_back_to_cwd(self) -> None:
        repo, wt = self._pair()
        missing = self.root / "nope"
        self.assertEqual(self.run_hook(f"git -C {missing} merge x", repo).returncode, 2)
        self.assertEqual(self.run_hook(f"git -C {missing} merge x", wt).returncode, 0)

    def test_bypass_rule_still_applies_with_dash_c(self) -> None:
        repo, wt = self._pair()
        self.assertEqual(
            self.run_hook(f"git -C {wt} commit --no-verify -m x", repo).returncode, 2,
        )

    # -- push to the primary branch: any checkout ---------------------------

    def test_denies_push_to_primary_branch_everywhere(self) -> None:
        repo, wt = self._pair()
        for cmd in (
            "git push origin HEAD:main",
            "git push origin feature/test:main",
            "git push origin feature/test:refs/heads/main",
            "git push origin main",
            "git push origin :main",
        ):
            for cwd in (repo, wt):
                with self.subTest(cmd=cmd, cwd=cwd.name):
                    self.assertEqual(self.run_hook(cmd, cwd).returncode, 2)

    def test_denies_bare_push_from_primary_branch(self) -> None:
        repo, wt = self._pair()
        self.assertEqual(self.run_hook("git push", repo).returncode, 2)
        self.assertEqual(self.run_hook("git push origin", repo).returncode, 2)
        self.assertEqual(self.run_hook("git push origin HEAD", repo).returncode, 2)
        self.assertEqual(self.run_hook("git push", wt).returncode, 0)
        self.assertEqual(self.run_hook("git push origin HEAD", wt).returncode, 0)

    def test_allows_push_to_feature_from_worktree(self) -> None:
        repo, wt = self._pair()
        for cmd in (
            "git push origin feature/test",
            "git push -u origin feature/test",
            "git push origin HEAD:feature/test",
            "git push origin main:feature/test",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, wt).returncode, 0)

    def test_primary_push_uses_effective_repo_for_bare_push(self) -> None:
        repo, wt = self._pair()
        self.assertEqual(self.run_hook(f"git -C {repo} push", wt).returncode, 2)
        self.assertEqual(self.run_hook(f"git -C {wt} push", repo).returncode, 0)

    def test_documented_land_work_push_forms_honour_marker(self) -> None:
        repo, wt = self._pair()
        for cmd in (
            "BENTO_LAND_WORK=1 git push origin HEAD:refs/heads/main",
            "BENTO_LAND_WORK=1 git -C /some/preview push origin HEAD:refs/heads/main",
            "BENTO_LAND_WORK=1 git push origin main",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, repo).returncode, 0)

    def test_push_primary_marker_and_opt_out(self) -> None:
        repo, wt = self._pair()
        self.assertEqual(
            self.run_hook("BENTO_LAND_WORK=1 git push origin HEAD:main", wt).returncode, 0,
        )
        (wt / ".agent-mode.local").write_text("require_worktree=false\n", encoding="utf-8")
        self.assertEqual(self.run_hook("git push origin HEAD:main", wt).returncode, 0)

    def test_denies_push_all_mirror_and_glob_refspecs(self) -> None:
        repo, wt = self._pair()
        for cmd in (
            "git push --all origin",
            "git push origin --mirror",
            "git push origin 'refs/heads/*:refs/heads/*'",
            "git push origin refs/heads/*:refs/heads/*",
        ):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_hook(cmd, wt).returncode, 2)

    def test_denies_bare_push_when_upstream_is_primary(self) -> None:
        repo, wt = self._pair()
        self._git(wt, "config", "push.default", "upstream")
        self._git(wt, "config", "branch.feature/test.remote", "origin")
        self._git(wt, "config", "branch.feature/test.merge", "refs/heads/main")
        self.assertEqual(self.run_hook("git push", wt).returncode, 2)

    def test_push_rule_skipped_when_primary_branch_undeterminable(self) -> None:
        repo = self._init_primary_repo()
        self._git(repo, "branch", "-m", "main", "trunk")
        wt = self.root / "worktree"
        self._git(repo, "worktree", "add", "-b", "feature/test", str(wt), "trunk")
        # No origin/HEAD and no main/master ref: the rule must not guess the
        # current branch (here the feature branch) as "primary".
        self.assertEqual(self.run_hook("git push origin feature/test", wt).returncode, 0)
        self.assertEqual(self.run_hook("git push origin HEAD", wt).returncode, 0)

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

    # -- bento-l01v: shared shell segmenter corpus, guard exit codes ---------

    def test_corpus_rows_that_invent_no_merge_are_allowed(self) -> None:
        # Quoted strings, heredoc bodies, a comment's dangling quote, and a
        # here-string that merely *mention* git text must not be blocked.
        repo = self._init_primary_repo()
        for row in (1, 2, 5, 6, 13, 15, 16):
            with self.subTest(row=row):
                result = self.run_hook(_corpus_command(row), repo)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_corpus_rows_with_a_real_merge_are_blocked(self) -> None:
        repo = self._init_primary_repo()
        for row in (3, 9, 10, 14, 17, 18, 19, 20, 21, 22, 23, 24, 27, 29, 31, 32, 33):
            with self.subTest(row=row):
                result = self.run_hook(_corpus_command(row), repo)
                self.assertEqual(result.returncode, 2, f"row {row}: {result.stderr}")

    def test_corpus_rows_where_the_merge_is_hidden_are_allowed(self) -> None:
        # Opaque ${...}, a substitution whose body never actually runs git,
        # a `{git` literal command name, and an array literal.
        repo = self._init_primary_repo()
        for row in (26, 28, 30, 36, 37):
            with self.subTest(row=row):
                result = self.run_hook(_corpus_command(row), repo)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_corpus_rows_with_grouped_or_case_merges_are_blocked(self) -> None:
        repo = self._init_primary_repo()
        for row in (34, 35, 38, 39):
            with self.subTest(row=row):
                result = self.run_hook(_corpus_command(row), repo)
                self.assertEqual(result.returncode, 2, f"row {row}: {result.stderr}")

    def test_process_substitution_body_is_a_true_positive(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("cat <(git merge x)", repo)
        self.assertEqual(result.returncode, 2)

    def test_unterminated_heredoc_is_allowed(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("cat <<EOF\ngit push --force", repo)
        self.assertEqual(result.returncode, 0)

    def test_corpus_rows_allowed_in_a_linked_worktree(self) -> None:
        repo = self._init_primary_repo()
        worktree = self._add_linked_worktree(repo)
        for row in (3, 10):
            with self.subTest(row=row):
                result = self.run_hook(_corpus_command(row), worktree)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_heredoc_no_verify_in_linked_worktree_allowed(self) -> None:
        repo = self._init_primary_repo()
        worktree = self._add_linked_worktree(repo)
        command = "cat > /tmp/x.md <<'EOF'\ngit commit --no-verify\nEOF"
        result = self.run_hook(command, worktree)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrapped_git_is_guarded(self) -> None:
        repo = self._init_primary_repo()
        result = self.run_hook("command git merge foo", repo)
        self.assertEqual(result.returncode, 2)
        result = self.run_hook("env GIT_X=1 git merge foo", repo)
        self.assertEqual(result.returncode, 2)

    def test_paren_pattern_inside_double_bracket_test_is_not_blocked(self) -> None:
        # Code review regression: '(...)' inside [[ ... ]] is extended-
        # pattern/grouping syntax, not a subshell -- it must not be
        # misread as a fabricated 'git merge'.
        repo = self._init_primary_repo()
        result = self.run_hook("[[ $x == (git merge) ]]", repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_hook("[[ $x == @(git merge foo) ]]", repo)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
