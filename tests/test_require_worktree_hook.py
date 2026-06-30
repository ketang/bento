import datetime
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
    / "require-worktree.sh"
)

BLOCKED_MESSAGE = (
    "Blocked: editing files directly on 'main' is not allowed.\n"
    "To disable this check for this repo, add 'require_worktree=false' to .agent-mode.local.\n"
)


class RequireWorktreeHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        # Neutral non-git directory used as the hook process CWD by default,
        # modeling production where Claude Code spawns hook processes from $HOME.
        self._hook_cwd_tmp = tempfile.TemporaryDirectory()
        self.hook_cwd = Path(self._hook_cwd_tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()
        self._hook_cwd_tmp.cleanup()

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    def _init_repo(self, branch: str = "main", name: str = "repo") -> Path:
        repo = self.root / name
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", branch)
        self._git(repo, "config", "user.name", "Require Worktree Test")
        self._git(repo, "config", "user.email", "require-worktree@example.com")
        (repo / "README.md").write_text("test\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def _run(
        self,
        cwd: Path | None = None,
        *,
        payload_cwd: Path | None = None,
        file_path: str | None = None,
        tool_name: str = "Write",
    ) -> subprocess.CompletedProcess[str]:
        """Run the hook with a neutral non-git process CWD by default.

        Hook processes run from $HOME in production, not the project root.
        Tests use a neutral non-git process CWD and pass the project directory
        via the JSON payload.

        cwd: override the process CWD. Defaults to ``self.hook_cwd``, a neutral
        non-git directory outside any git repo.
        payload_cwd: if given, embed it as the ``cwd`` field in the stdin JSON
        payload, simulating how Claude Code sends the project directory to hooks
        even when the hook process itself starts from $HOME.
        file_path: if given, embed it as ``tool_input.file_path`` so the hook
        can evaluate the target path's repo rather than only the session cwd.
        """
        if cwd is None:
            cwd = self.hook_cwd
        import json as _json
        payload: dict = {}
        if payload_cwd is not None:
            payload["cwd"] = str(payload_cwd)
        if file_path is not None:
            payload["tool_name"] = tool_name
            payload["tool_input"] = {"file_path": file_path}
        stdin = _json.dumps(payload) + "\n"
        return subprocess.run(
            [str(HOOK_SCRIPT)],
            input=stdin,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_blocks_main_without_opt_out(self) -> None:
        repo = self._init_repo()

        result = self._run(payload_cwd=repo)

        # Exit code 2 is the documented PreToolUse blocking signal for both
        # Claude Code and Codex. Exit code 1 is classified as a non-blocking
        # failure and lets the tool call proceed; asserting != 0 is not
        # enough to catch that regression, so assert exactly 2.
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertNotEqual(
            result.returncode,
            1,
            msg="exit 1 is non-blocking in PreToolUse; hook must exit 2",
        )
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_allows_opt_out(self) -> None:
        repo = self._init_repo()
        (repo / ".agent-mode.local").write_text(
            "# local agent mode\nrequire_worktree=false\n",
            encoding="utf-8",
        )

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_blocks_when_opt_out_key_absent_or_other_value(self) -> None:
        repo = self._init_repo()
        (repo / ".agent-mode.local").write_text(
            "other=true\nrequire_worktree=true\n",
            encoding="utf-8",
        )

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_allows_non_git_directory(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()

        result = self._run(payload_cwd=plain)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_detached_head(self) -> None:
        repo = self._init_repo()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._git(repo, "checkout", "-q", "--detach", commit)

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_non_main_branch(self) -> None:
        repo = self._init_repo()
        self._git(repo, "checkout", "-q", "-b", "pp-abc")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    # --- Tests for real production path: hook process CWD != project directory ---
    # Claude Code runs hook processes from $HOME, not the project root.
    # The hook must read the project directory from the stdin JSON payload.

    def test_blocks_main_when_hook_cwd_is_outside_repo(self) -> None:
        repo = self._init_repo()

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_allows_opt_out_when_hook_cwd_is_outside_repo(self) -> None:
        repo = self._init_repo()
        (repo / ".agent-mode.local").write_text(
            "require_worktree=false\n", encoding="utf-8"
        )

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_non_main_branch_when_hook_cwd_is_outside_repo(self) -> None:
        repo = self._init_repo()
        self._git(repo, "checkout", "-q", "-b", "feature-xyz")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_non_git_payload_cwd(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()

        result = self._run(payload_cwd=plain)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    # --- Tests for target-path containment (bento-s5h) ---
    # The hook must evaluate the repo that contains the *target* file, not just
    # the session cwd. Writes to paths outside any protected repo (e.g. /tmp,
    # another repo on a feature branch) must be allowed even while the session
    # cwd sits on main.

    def test_allows_write_to_path_outside_repo_on_main(self) -> None:
        repo = self._init_repo()
        # Absolute target outside any git repo, while the session cwd is on main.
        outside = self.root / "scratch.md"

        result = self._run(payload_cwd=repo, file_path=str(outside))

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_write_to_nonexistent_dir_outside_repo_on_main(self) -> None:
        repo = self._init_repo()
        # Neither the file nor its parent dir exists yet, and both are outside
        # any repo. The hook must walk up to the nearest existing ancestor.
        outside = self.root / "tmpdir" / "nested" / "draft.md"

        result = self._run(payload_cwd=repo, file_path=str(outside))

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_blocks_write_to_in_repo_path_on_main(self) -> None:
        repo = self._init_repo()
        target = repo / "catalog" / "newfile.py"

        result = self._run(payload_cwd=repo, file_path=str(target))

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_blocks_relative_in_repo_path_on_main(self) -> None:
        repo = self._init_repo()
        # Relative target resolves against the payload cwd (the repo on main).
        result = self._run(payload_cwd=repo, file_path="catalog/foo.py")

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_target_in_other_repo_on_main_is_blocked(self) -> None:
        # Session cwd is on a feature branch; target lives in a different repo
        # that is on main. The hook evaluates the *target* repo's branch.
        session = self._init_repo(branch="feature-x", name="session")
        other = self._init_repo(branch="main", name="other")
        target = other / "file.txt"

        result = self._run(payload_cwd=session, file_path=str(target))

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_target_in_other_repo_on_feature_is_allowed(self) -> None:
        # Session cwd is on main; target lives in a different repo on a feature
        # branch. The target repo's branch governs, so the write is allowed.
        session = self._init_repo(branch="main", name="session")
        other = self._init_repo(branch="feature-y", name="other")
        target = other / "file.txt"

        result = self._run(payload_cwd=session, file_path=str(target))

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    # --- Tests for markdown exemption (bento-6cc) ---
    # Plan files, specs, and notes (.md / .markdown) are low-risk and should be
    # writable on main without a feature branch. Other file types stay blocked.

    def test_allows_md_write_on_main(self) -> None:
        repo = self._init_repo()
        target = repo / "docs" / "plan.md"

        result = self._run(payload_cwd=repo, file_path=str(target), tool_name="Write")

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_md_edit_on_main(self) -> None:
        repo = self._init_repo()
        target = repo / "README.md"

        result = self._run(payload_cwd=repo, file_path=str(target), tool_name="Edit")

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_markdown_extension_on_main(self) -> None:
        repo = self._init_repo()
        target = repo / "notes.markdown"

        result = self._run(payload_cwd=repo, file_path=str(target), tool_name="Write")

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_uppercase_md_extension_on_main(self) -> None:
        repo = self._init_repo()
        target = repo / "README.MD"

        result = self._run(payload_cwd=repo, file_path=str(target), tool_name="Write")

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_blocks_py_write_on_main(self) -> None:
        repo = self._init_repo()
        target = repo / "script.py"

        result = self._run(payload_cwd=repo, file_path=str(target), tool_name="Write")

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_blocks_ts_edit_on_main(self) -> None:
        repo = self._init_repo()
        target = repo / "app.ts"

        result = self._run(payload_cwd=repo, file_path=str(target), tool_name="Edit")

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_blocks_bash_on_main(self) -> None:
        # A Bash tool call has no file_path; it must stay blocked on main even
        # though the markdown exemption exists for Write/Edit.
        repo = self._init_repo()

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertEqual(result.stderr, BLOCKED_MESSAGE)

    def test_help_flags(self) -> None:
        for flag in ("-h", "--help"):
            result = subprocess.run(
                [str(HOOK_SCRIPT), flag],
                cwd=self.hook_cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("require-worktree", result.stdout)


class RequireWorktreeHookAuditTest(unittest.TestCase):
    """Audit logging: verify rejection records written to daily JSONL."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._hook_cwd_tmp = tempfile.TemporaryDirectory()
        self.hook_cwd = Path(self._hook_cwd_tmp.name).resolve()
        # Fake HOME so audit writes go to an isolated directory.
        self.fake_home = self.root / "home"
        self.fake_home.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()
        self._hook_cwd_tmp.cleanup()

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    def _init_repo(self, branch: str = "main") -> Path:
        repo = self.root / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", branch)
        self._git(repo, "config", "user.name", "Audit Test")
        self._git(repo, "config", "user.email", "audit-test@example.com")
        (repo / "README.md").write_text("test\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def _run(self, payload: dict, *, repo_cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(self.fake_home)
        stdin = json.dumps(payload) + "\n"
        return subprocess.run(
            [str(HOOK_SCRIPT)],
            input=stdin,
            cwd=repo_cwd or self.hook_cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _today_log(self) -> Path:
        # Glob for the rejection log instead of recomputing today's date after
        # the hook already ran: a midnight rollover between the hook's write
        # and this call would otherwise resolve to the wrong filename.
        hooks_dir = self.fake_home / ".claude" / "hooks"
        matches = sorted(hooks_dir.glob("require-worktree-rejections.*.jsonl"))
        if matches:
            return matches[0]
        # No log was written; return today's path so `.exists()` is False and
        # failure messages still name a plausible file.
        date_str = datetime.date.today().isoformat()
        return hooks_dir / f"require-worktree-rejections.{date_str}.jsonl"

    def test_audit_log_written_on_rejection(self) -> None:
        repo = self._init_repo()

        result = self._run({"cwd": str(repo), "tool_name": "Write", "tool_input": {"file_path": "x.py"}})

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        log = self._today_log()
        self.assertTrue(log.exists(), msg=f"audit log not found at {log}")

    def test_audit_log_contains_correct_fields(self) -> None:
        repo = self._init_repo()
        payload = {
            "cwd": str(repo),
            "session_id": "sess-abc123",
            "tool_name": "Write",
            "tool_input": {"file_path": "catalog/foo.py", "content": "big"},
        }

        self._run(payload)

        record = json.loads(self._today_log().read_text().splitlines()[0])
        self.assertIn("timestamp", record)
        self.assertEqual(record["session_id"], "sess-abc123")
        self.assertEqual(record["tool_name"], "Write")
        self.assertEqual(record["cwd"], str(repo))
        self.assertEqual(record["branch"], "main")
        self.assertIn("repo_root", record)
        self.assertIn("tool_input", record)

    def test_audit_log_strips_large_fields(self) -> None:
        repo = self._init_repo()
        payload = {
            "cwd": str(repo),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "foo.py",
                "old_string": "old" * 1000,
                "new_string": "new" * 1000,
            },
        }

        self._run(payload)

        record = json.loads(self._today_log().read_text().splitlines()[0])
        ti = record["tool_input"]
        self.assertEqual(ti.get("file_path"), "foo.py")
        self.assertNotIn("old_string", ti)
        self.assertNotIn("new_string", ti)

    def test_audit_log_uses_payload_cwd_not_process_cwd(self) -> None:
        repo = self._init_repo()
        # Process CWD is hook_cwd (a non-git temp dir); payload carries the repo.
        result = self._run({"cwd": str(repo), "tool_name": "Write", "tool_input": {}}, repo_cwd=self.hook_cwd)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        record = json.loads(self._today_log().read_text().splitlines()[0])
        self.assertEqual(record["cwd"], str(repo))

    def test_no_audit_log_when_allowed(self) -> None:
        repo = self._init_repo()
        self._git(repo, "checkout", "-q", "-b", "feature-x")

        result = self._run({"cwd": str(repo), "tool_name": "Write", "tool_input": {}})

        self.assertEqual(result.returncode, 0)
        self.assertFalse(self._today_log().exists(), msg="audit log should not be written when hook allows")

    def test_audit_appends_multiple_records(self) -> None:
        repo = self._init_repo()
        payload = {"cwd": str(repo), "tool_name": "Write", "tool_input": {"file_path": "a.py"}}

        self._run(payload)
        self._run(payload)

        lines = [l for l in self._today_log().read_text().splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)


class RequireWorktreeBlockingExitCodeRegressionTest(unittest.TestCase):
    """Regression guard for bento-fko.

    The require-worktree PreToolUse hook originally ended with ``exit 1``,
    which both Claude Code and Codex classify as a non-blocking failure: the
    stderr message is logged but the tool call proceeds. The blocking
    contract requires either ``exit 2`` (with the reason on stderr) or a
    JSON deny decision on stdout. This test pins the exit code so the hook
    cannot silently regress back to 1 (or any other non-blocking value).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self._hook_cwd_tmp = tempfile.TemporaryDirectory()
        self.hook_cwd = Path(self._hook_cwd_tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()
        self._hook_cwd_tmp.cleanup()

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    def _init_main_repo(self) -> Path:
        repo = self.root / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.name", "Regression Test")
        self._git(repo, "config", "user.email", "regression@example.com")
        (repo / "README.md").write_text("x\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def test_blocking_exit_code_is_exactly_2(self) -> None:
        repo = self._init_main_repo()
        stdin = json.dumps({"cwd": str(repo)}) + "\n"
        result = subprocess.run(
            [str(HOOK_SCRIPT)],
            input=stdin,
            cwd=self.hook_cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            2,
            msg=(
                "PreToolUse must exit 2 to actually block; "
                f"got rc={result.returncode}, stderr={result.stderr!r}"
            ),
        )

    def test_blocking_exit_code_is_not_1(self) -> None:
        repo = self._init_main_repo()
        stdin = json.dumps({"cwd": str(repo)}) + "\n"
        result = subprocess.run(
            [str(HOOK_SCRIPT)],
            input=stdin,
            cwd=self.hook_cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(
            result.returncode,
            1,
            msg=(
                "exit 1 is classified as a non-blocking PreToolUse failure "
                "by both Claude Code and Codex; the hook never blocks any "
                "edit at this exit code (bento-fko)."
            ),
        )


if __name__ == "__main__":
    unittest.main()
