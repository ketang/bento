import json
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
    / "check-unpushed.py"
)


class CheckUnpushedHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        # Neutral non-git directory used as the hook process CWD, modeling
        # production where Claude Code spawns hook processes from $HOME. The
        # project directory is always passed via the JSON payload's cwd field.
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
        self._git(repo, "config", "user.name", "Check Unpushed Test")
        self._git(repo, "config", "user.email", "check-unpushed@example.com")
        (repo / "README.md").write_text("test\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def _add_remote(self, repo: Path, branch: str = "main") -> Path:
        """Create a bare remote and push branch, setting upstream tracking."""
        remote = self.root / (repo.name + "-remote.git")
        subprocess.run(
            ["git", "init", "--bare", "-q", str(remote)],
            check=True,
            capture_output=True,
            text=True,
        )
        self._git(repo, "remote", "add", "origin", str(remote))
        self._git(repo, "push", "-q", "-u", "origin", branch)
        return remote

    def _run(
        self,
        *,
        payload_cwd: Path | None = None,
        cwd: Path | None = None,
        stop_hook_active: bool = False,
        include_cwd: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if cwd is None:
            cwd = self.hook_cwd
        payload: dict = {}
        if include_cwd and payload_cwd is not None:
            payload["cwd"] = str(payload_cwd)
        if stop_hook_active:
            payload["stop_hook_active"] = True
        stdin = json.dumps(payload) + "\n"
        return subprocess.run(
            [str(HOOK_SCRIPT)],
            input=stdin,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

    # --- Blocking cases: exit exactly 2 (not 1 — exit 1 is non-blocking) ---

    def test_blocks_dirty_tree(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        # Tracked file modified but not committed -> dirty, up to date otherwise.
        (repo / "README.md").write_text("changed\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertNotEqual(
            result.returncode,
            1,
            msg="exit 1 is non-blocking for Stop; hook must exit 2",
        )
        self.assertIn("uncommitted changes", result.stderr)
        self.assertIn("main", result.stderr)

    def test_blocks_untracked_file(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "stray.txt").write_text("stray\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_blocks_ahead_of_upstream(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        # New local commit not pushed -> ahead by 1, clean tree.
        (repo / "README.md").write_text("v2\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "second")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("1 unpushed commit", result.stderr)
        self.assertIn("main", result.stderr)

    def test_blocks_multiple_ahead_plural(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        for i in range(2):
            (repo / "README.md").write_text(f"v{i}\n", encoding="utf-8")
            self._git(repo, "commit", "-aqm", f"c{i}")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("2 unpushed commits", result.stderr)

    def test_blocks_dirty_and_ahead(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("v2\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "second")
        (repo / "README.md").write_text("v3-uncommitted\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)
        self.assertIn("1 unpushed commit", result.stderr)

    # --- Allowing cases: exit 0, silent ---

    def test_allows_clean_pushed_tree(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_allows_no_upstream_clean_feature_branch(self) -> None:
        # A feature branch with a commit but no upstream must not be trapped:
        # a missing upstream is a warning, not a block, when the tree is clean.
        repo = self._init_repo(branch="feature-x")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_blocks_no_upstream_when_dirty(self) -> None:
        # No upstream still blocks on a dirty tree (dirty is independent of push
        # state). Guards against a "no upstream => always allow" regression.
        repo = self._init_repo(branch="feature-x")
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_allows_non_git_cwd(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()

        result = self._run(payload_cwd=plain)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_allows_missing_cwd(self) -> None:
        result = self._run(include_cwd=False)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_stop_hook_active_reentrancy(self) -> None:
        # Even with a dirty tree, a re-entrant Stop invocation must not block,
        # so a blocking stop never loops forever.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        result = self._run(payload_cwd=repo, stop_hook_active=True)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_opt_out_via_agent_mode_local(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")
        (repo / ".agent-mode.local").write_text(
            "require_pushed=false\n", encoding="utf-8"
        )

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_allows_land_work_preview_worktree(self) -> None:
        # A land-work merge preview is a detached-HEAD worktree whose staged
        # changes are the merge candidate under review, not stranded work.
        # land-work-create-preview.py names it "land-work-preview-<random>".
        repo = self._init_repo()
        self._add_remote(repo)

        preview_dir = self.root / "land-work-preview-abc123"
        self._git(repo, "worktree", "add", "--detach", str(preview_dir), "main")
        self._git(preview_dir, "merge", "--no-ff", "--no-commit", "main")
        (preview_dir / "stray.txt").write_text("staged\n", encoding="utf-8")
        self._git(preview_dir, "add", "stray.txt")

        result = self._run(payload_cwd=preview_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_blocks_reused_leaked_preview_directory(self) -> None:
        # A failed/interrupted landing can leak a land-work-preview-* worktree
        # (bento-gd2) that survives until a manual closure sweep. If that
        # directory is reused for real work — checked out to an attached
        # branch and committed to — before the sweep runs, the basename alone
        # must not make the hook skip it: HEAD is attached, so this is not a
        # live preview and genuinely unpushed work here must still block.
        repo = self._init_repo()
        self._add_remote(repo)

        leaked_dir = self.root / "land-work-preview-leaked1"
        self._git(repo, "worktree", "add", "--detach", str(leaked_dir), "main")
        self._git(leaked_dir, "checkout", "-b", "reused-feature")
        (leaked_dir / "README.md").write_text("reused-work\n", encoding="utf-8")

        result = self._run(payload_cwd=leaked_dir)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_blocks_fake_merge_head_marker(self) -> None:
        # A bare `touch .git/MERGE_HEAD` must not bypass the check: the
        # marker's content has to resolve to a real commit, not just exist.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")
        (repo / ".git" / "MERGE_HEAD").write_text("not-a-real-sha\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_blocks_fake_rebase_merge_marker(self) -> None:
        # A bare `mkdir .git/rebase-merge` (no real rebase state, HEAD still
        # attached) must not bypass the check either.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")
        (repo / ".git" / "rebase-merge").mkdir()

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_allows_in_progress_rebase_in_linked_worktree(self) -> None:
        # A rebase mid-replay detaches HEAD and stages files in the linked
        # worktree; that is normal in-protocol state, not abandoned work.
        repo = self._init_repo()
        self._add_remote(repo)
        self._git(repo, "checkout", "-b", "feature")
        (repo / "README.md").write_text("feature-change\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "feature commit")
        self._git(repo, "checkout", "main")
        (repo / "README.md").write_text("main-change\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "main commit")

        worktree_dir = self.root / "feature-worktree"
        self._git(repo, "worktree", "add", str(worktree_dir), "feature")
        # Both branches touched README.md differently, so rebasing feature
        # onto main conflicts and stops mid-replay with a detached HEAD and
        # unresolved/staged changes in the linked worktree.
        subprocess.run(
            ["git", "rebase", "main"],
            cwd=worktree_dir,
            capture_output=True,
            text=True,
            check=False,
        )

        result = self._run(payload_cwd=worktree_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_blocks_unpushed_commits_in_linked_worktree(self) -> None:
        # A linked worktree on an attached branch with real unpushed commits
        # is exactly the case the preview/rebase skips must not swallow.
        repo = self._init_repo()
        self._add_remote(repo)
        self._git(repo, "branch", "feature", "main")
        self._git(repo, "push", "-q", "-u", "origin", "feature")

        worktree_dir = self.root / "feature-worktree"
        self._git(repo, "worktree", "add", str(worktree_dir), "feature")
        (worktree_dir / "README.md").write_text("feature-work\n", encoding="utf-8")
        self._git(worktree_dir, "commit", "-aqm", "feature commit")

        result = self._run(payload_cwd=worktree_dir)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("1 unpushed commit", result.stderr)
        self.assertIn("feature", result.stderr)

    def test_uses_payload_cwd_not_process_cwd(self) -> None:
        # Process CWD is a neutral non-git temp dir; the dirty repo is carried
        # only in the payload cwd, mirroring Claude Code spawning hooks from
        # $HOME. The hook must evaluate the payload cwd's repo.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        result = self._run(payload_cwd=repo, cwd=self.hook_cwd)

        self.assertEqual(result.returncode, 2, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
