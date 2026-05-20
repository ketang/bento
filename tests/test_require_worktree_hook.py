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

    def _init_repo(self, branch: str = "main") -> Path:
        repo = self.root / "repo"
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
        """
        if cwd is None:
            cwd = self.hook_cwd
        if payload_cwd is not None:
            import json as _json
            stdin = _json.dumps({"cwd": str(payload_cwd)}) + "\n"
        else:
            stdin = "{}\n"
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

        self.assertNotEqual(result.returncode, 0)
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

        self.assertNotEqual(result.returncode, 0)
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

        self.assertNotEqual(result.returncode, 0)
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


if __name__ == "__main__":
    unittest.main()
