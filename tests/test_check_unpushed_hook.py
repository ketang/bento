import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPTS = (
    REPO_ROOT / "catalog" / "hooks" / "bento" / "claude" / "scripts" / "check-unpushed.py",
    REPO_ROOT / "catalog" / "hooks" / "bento" / "codex" / "scripts" / "check-unpushed.py",
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

    def _write_beads_state(self, repo: Path, relative_path: str) -> Path:
        path = repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("state\n", encoding="utf-8")
        return path

    def _commit_all(self, repo: Path, message: str) -> None:
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-qm", message)

    def _seed_beads_operational_paths(self, repo: Path) -> None:
        self._write_beads_state(repo, ".beads/interactions.jsonl")
        self._write_beads_state(repo, ".beads/backup/backup_state.json")
        self._commit_all(repo, "seed beads state")
        self._git(repo, "push", "-q")

    def _write_repo_scope_exempt_paths(self, repo: Path, content: str) -> None:
        """Write the agent-plugins repo-scope override for check-unpushed's
        dirty-state-exempt-paths customization file (marketplace/plugin
        "bento"/"bento")."""
        path = repo / ".agent-plugins" / "bento" / "bento" / "check-unpushed" / "dirty-state-exempt-paths.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_home_scope_exempt_paths(self, content: str) -> None:
        """Write the agent-plugins home-scope override, under the same
        isolated XDG_CONFIG_HOME every _run() call in this test uses."""
        path = (
            self.root
            / "config-home"
            / "agent-plugins"
            / "bento"
            / "bento"
            / "check-unpushed"
            / "dirty-state-exempt-paths.txt"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _run(
        self,
        *,
        payload_cwd: Path | None = None,
        cwd: Path | None = None,
        stop_hook_active: bool = False,
        include_cwd: bool = True,
        session_id: str | None = None,
        runtime_base: Path | str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if cwd is None:
            cwd = self.hook_cwd
        payload: dict = {}
        if include_cwd and payload_cwd is not None:
            payload["cwd"] = str(payload_cwd)
        if stop_hook_active:
            payload["stop_hook_active"] = True
        if session_id is not None:
            payload["session_id"] = session_id
        stdin = json.dumps(payload) + "\n"
        results = []
        for script in HOOK_SCRIPTS:
            # Each peer script (claude/codex) gets its own throttle-marker
            # directory, keyed by its own parent dir name -- otherwise the
            # first script's write would silently suppress the second
            # script's advisory within the same _run() call and break the
            # cross-peer equality assertion below, even though the two
            # scripts are independently correct.
            runtime_dir = (
                Path(runtime_base)
                if runtime_base is not None
                else self.root / "runtime" / script.parent.parent.name
            )
            runtime_dir.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["XDG_RUNTIME_DIR"] = str(runtime_dir)
            # Isolate home-scope agent-plugins lookups from this machine's
            # real ~/.config, so a stray local override can never leak into
            # these tests and the "no config anywhere" case is reproducible.
            config_home = self.root / "config-home"
            config_home.mkdir(parents=True, exist_ok=True)
            env["XDG_CONFIG_HOME"] = str(config_home)
            results.append(
                subprocess.run(
                    [str(script)],
                    input=stdin,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
            )
        reference = results[0]
        for script, result in zip(HOOK_SCRIPTS[1:], results[1:]):
            self.assertEqual(result.returncode, reference.returncode, script)
            self.assertEqual(result.stderr, reference.stderr, script)
        return reference

    def _grant_one_turn_hold(self, session_id: str) -> None:
        """Allow exactly one Stop boundary for each peer hook runtime."""
        for script in HOOK_SCRIPTS:
            runtime_dir = self.root / "runtime" / script.parent.parent.name
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / f"bento-check-unpushed-hold-{session_id}").touch()

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

    def test_allows_one_turn_hold_for_coordinating_subagent(self) -> None:
        # A lead can direct one teammate to create this session-scoped marker
        # before it yields, preserving an explicit temporary hold without
        # disabling the protection for other worktrees or later turns.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("held for lead decision\n", encoding="utf-8")
        session_id = "subagent-hold-1"
        self._grant_one_turn_hold(session_id)

        first = self._run(payload_cwd=repo, session_id=session_id)
        second = self._run(payload_cwd=repo, session_id=session_id)

        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(first.stderr, "")
        self.assertEqual(second.returncode, 2, msg=second.stderr)
        self.assertIn("uncommitted changes", second.stderr)

    def test_relative_runtime_dir_cannot_place_hold_marker_in_process_cwd(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")
        # A distinct session_id per peer script, not the shared cross-peer
        # `_run()` helper: with runtime_base="." forcing a relative
        # XDG_RUNTIME_DIR, _runtime_dir() rejects it and both scripts fall
        # back to the same /tmp regardless of runtime_base. A shared
        # session_id would then let the first script's block-state write
        # (bento-neng) be observed by the second script's read, which is a
        # sequencing artifact of this test (two subprocess calls sharing one
        # fallback directory), not a real claude/codex behavioral difference
        # -- both scripts are byte-identical files.
        for index, script in enumerate(HOOK_SCRIPTS):
            session_id = f"relative-runtime-1-{index}"
            marker = self.hook_cwd / f"bento-check-unpushed-hold-{session_id}"
            marker.touch()
            env = os.environ.copy()
            env["XDG_RUNTIME_DIR"] = "."
            result = subprocess.run(
                [str(script)],
                input=json.dumps({"cwd": str(repo), "session_id": session_id}) + "\n",
                cwd=self.hook_cwd,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 2, msg=(script, result.stderr))
            self.assertTrue(marker.exists(), script)

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

    def test_allows_dirty_beads_operational_state(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        self._seed_beads_operational_paths(repo)
        self._write_beads_state(repo, ".beads/interactions.jsonl").write_text(
            "changed\n", encoding="utf-8"
        )

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_fails_closed_when_agent_plugins_resolver_is_unlocatable(self) -> None:
        # bento-7u37: a hook shipped without the launch-work skill's scripts/
        # (or after a relative-layout refactor) cannot import
        # agent_plugins_resolver.py. It must degrade to "nothing is exempt"
        # -- Beads-only dirty state then blocks -- rather than crash or
        # silently exempt everything. Every other test runs the hook from
        # inside the checkout, where the resolver is always found.
        repo = self._init_repo()
        self._add_remote(repo)
        self._seed_beads_operational_paths(repo)
        self._write_beads_state(repo, ".beads/interactions.jsonl").write_text(
            "changed\n", encoding="utf-8"
        )
        for script in HOOK_SCRIPTS:
            isolated = self.root / f"isolated-{script.parent.parent.name}" / "a" / "b" / "c" / "scripts"
            isolated.mkdir(parents=True)
            copy = isolated / script.name
            copy.write_bytes(script.read_bytes())
            copy.chmod(0o755)

            result = subprocess.run(
                [str(copy)],
                input=json.dumps({"cwd": str(repo)}) + "\n",
                cwd=self.hook_cwd,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2, msg=(script, result.stderr))
            self.assertIn("uncommitted changes", result.stderr)

    def test_blocks_mixed_dirty_beads_and_source_state(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        self._seed_beads_operational_paths(repo)
        self._write_beads_state(repo, ".beads/backup/backup_state.json").write_text(
            "changed\n", encoding="utf-8"
        )
        (repo / "README.md").write_text("changed\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_allows_ahead_beads_operational_state(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        self._seed_beads_operational_paths(repo)
        self._write_beads_state(repo, ".beads/interactions.jsonl").write_text(
            "changed\n", encoding="utf-8"
        )
        self._commit_all(repo, "Beads: sync tracker state")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_allows_dirty_and_ahead_when_both_touch_only_exempt_paths(self) -> None:
        # bento-4cyj: patterns are resolved once and shared by the dirty and
        # ahead-commit checks; both must still honor them in one invocation.
        repo = self._init_repo()
        self._add_remote(repo)
        self._seed_beads_operational_paths(repo)
        self._write_beads_state(repo, ".beads/interactions.jsonl").write_text(
            "changed\n", encoding="utf-8"
        )
        self._commit_all(repo, "Beads: sync tracker state")
        self._write_beads_state(repo, ".beads/backup/backup_state.json").write_text(
            "changed\n", encoding="utf-8"
        )

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_blocks_mixed_ahead_beads_and_source_state(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        self._seed_beads_operational_paths(repo)
        self._write_beads_state(repo, ".beads/interactions.jsonl").write_text(
            "changed\n", encoding="utf-8"
        )
        self._commit_all(repo, "Beads: sync tracker state")
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "source change")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("2 unpushed commits", result.stderr)

    # --- Generic tracker-exemption mechanism (agent-plugins convention) ---
    # check-unpushed itself hardcodes no tracker's file layout; exemptions
    # are resolved via marketplace "bento", plugin "bento", customization
    # file "check-unpushed/dirty-state-exempt-paths.txt". The Beads paths
    # above are exercised through this hook's *bundled default* for that
    # file, not through code specific to Beads.

    def test_allows_repo_scope_custom_exempt_pattern(self) -> None:
        # Untracked changes fail closed regardless of pattern (same rule the
        # Beads-specific exemption always enforced), so seed the path as a
        # tracked file first and then modify it, matching
        # _seed_beads_operational_paths' shape for its own paths.
        repo = self._init_repo()
        self._add_remote(repo)
        self._write_repo_scope_exempt_paths(repo, "notes/scratch-*.md\n")
        (repo / "notes").mkdir()
        (repo / "notes" / "scratch-1.md").write_text("seed\n", encoding="utf-8")
        self._commit_all(repo, "add repo-scope exemption config and seed notes")
        self._git(repo, "push", "-q")
        (repo / "notes" / "scratch-1.md").write_text("wip\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_repo_scope_override_replaces_bundled_beads_default(self) -> None:
        # A repo-scope override is a full replacement of the resolved file,
        # not an addition to the bundled default -- once a repo configures
        # its own tracker's exemptions, an unrelated tracker's operational
        # files (here, Beads') are no longer exempt unless also listed.
        repo = self._init_repo()
        self._add_remote(repo)
        self._seed_beads_operational_paths(repo)
        self._write_repo_scope_exempt_paths(repo, "notes/*.md\n")
        self._commit_all(repo, "add repo-scope exemption config")
        self._git(repo, "push", "-q")
        self._write_beads_state(repo, ".beads/interactions.jsonl").write_text(
            "changed\n", encoding="utf-8"
        )

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_allows_home_scope_custom_exempt_pattern_without_repo_scope(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        self._write_home_scope_exempt_paths("cache/*.tmp\n")
        (repo / "cache").mkdir()
        (repo / "cache" / "x.tmp").write_text("seed\n", encoding="utf-8")
        self._commit_all(repo, "seed cache")
        self._git(repo, "push", "-q")
        (repo / "cache" / "x.tmp").write_text("junk\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_repo_scope_exempt_paths_overrides_home_scope(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        self._write_home_scope_exempt_paths("home-only/*.tmp\n")
        self._write_repo_scope_exempt_paths(repo, "repo-only/*.tmp\n")
        (repo / "home-only").mkdir()
        (repo / "home-only" / "x.tmp").write_text("seed\n", encoding="utf-8")
        self._commit_all(repo, "add repo-scope exemption config and seed home-only")
        self._git(repo, "push", "-q")
        (repo / "home-only" / "x.tmp").write_text("junk\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        # The home-scope pattern is not in effect: repo scope exists (even
        # though its own pattern doesn't match this path) and wins outright.
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_allows_ahead_commits_matching_repo_scope_pattern(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        self._write_repo_scope_exempt_paths(repo, "notes/*.md\n")
        self._commit_all(repo, "add repo-scope exemption config")
        self._git(repo, "push", "-q")
        (repo / "notes").mkdir()
        (repo / "notes" / "a.md").write_text("wip\n", encoding="utf-8")
        self._commit_all(repo, "notes: wip")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_blocks_empty_ahead_commit(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        self._git(repo, "commit", "--allow-empty", "-qm", "empty commit")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
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

    def test_allows_configured_integration_worktree(self) -> None:
        # A repo-configured landing.integration_worktree (bento-96ua.1) has a
        # user-chosen name and path, so the name-prefix check alone would
        # miss it. It never accumulates real work of its own — every commit
        # or staged change inside it is fully reproducible by re-running the
        # merge preview — so it must be exempt from the block just like a
        # scratch land-work-preview-* worktree.
        repo = self._init_repo()
        self._add_remote(repo)

        integration_dir = self.root / "integration-worktree"
        (repo / "swarm-config.json").write_text(
            json.dumps({"landing": {"integration_worktree": str(integration_dir)}}),
            encoding="utf-8",
        )
        self._commit_all(repo, "add swarm config")
        self._git(repo, "push", "-q")

        self._git(repo, "worktree", "add", "--detach", str(integration_dir), "main")
        self._git(integration_dir, "merge", "--no-ff", "--no-commit", "main")
        (integration_dir / "stray.txt").write_text("staged\n", encoding="utf-8")
        self._git(integration_dir, "add", "stray.txt")

        result = self._run(payload_cwd=integration_dir)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_blocks_configured_integration_worktree_with_foreign_untracked_file(self) -> None:
        # Regression: nothing in this worktree's own lifecycle produces an
        # untracked, non-ignored file (land-work-create-preview.py's
        # integration_worktree_unusable_reason() refuses to reuse it for
        # exactly this reason). Its presence means a person or another tool
        # put real, non-reproducible work there, so the path-match exemption
        # alone must not silently let the session end — that would let
        # land-work's next `git reset --hard` discard it unnoticed.
        repo = self._init_repo()
        self._add_remote(repo)

        integration_dir = self.root / "integration-worktree"
        (repo / "swarm-config.json").write_text(
            json.dumps({"landing": {"integration_worktree": str(integration_dir)}}),
            encoding="utf-8",
        )
        self._commit_all(repo, "add swarm config")
        self._git(repo, "push", "-q")

        self._git(repo, "worktree", "add", "--detach", str(integration_dir), "main")
        (integration_dir / "real-work.txt").write_text("not reproducible\n", encoding="utf-8")

        result = self._run(payload_cwd=integration_dir)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_blocks_worktree_not_matching_configured_integration_worktree(self) -> None:
        # A worktree that merely sits near a repo declaring
        # landing.integration_worktree, but is not that exact configured
        # path, must not be exempted just because the config exists.
        repo = self._init_repo()
        self._add_remote(repo)

        integration_dir = self.root / "integration-worktree"
        (repo / "swarm-config.json").write_text(
            json.dumps({"landing": {"integration_worktree": str(integration_dir)}}),
            encoding="utf-8",
        )
        self._commit_all(repo, "add swarm config")
        self._git(repo, "push", "-q")

        other_dir = self.root / "other-worktree"
        self._git(repo, "worktree", "add", "-b", "other-branch", str(other_dir), "main")
        (other_dir / "README.md").write_text("real work\n", encoding="utf-8")

        result = self._run(payload_cwd=other_dir)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

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

    def test_blocks_self_referential_merge_head(self) -> None:
        # `git rev-parse HEAD > .git/MERGE_HEAD` resolves to a real commit,
        # but HEAD is its own ancestor: a genuine incoming merge parent is
        # never already reachable from HEAD, so this must not bypass the
        # check either.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        (repo / ".git" / "MERGE_HEAD").write_text(head_sha, encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("uncommitted changes", result.stderr)

    def test_allows_octopus_merge_multi_line_merge_head(self) -> None:
        # A real octopus merge writes one SHA per non-first parent, newline
        # separated, into MERGE_HEAD. Each line must be validated
        # independently rather than the whole content as a single ref.
        repo = self._init_repo()
        self._add_remote(repo)
        self._git(repo, "checkout", "-b", "branch-a")
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        self._git(repo, "add", "a.txt")
        self._git(repo, "commit", "-qm", "branch-a commit")
        branch_a_sha = subprocess.run(
            ["git", "rev-parse", "branch-a"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self._git(repo, "checkout", "main")
        self._git(repo, "checkout", "-b", "branch-b")
        (repo / "b.txt").write_text("b\n", encoding="utf-8")
        self._git(repo, "add", "b.txt")
        self._git(repo, "commit", "-qm", "branch-b commit")
        branch_b_sha = subprocess.run(
            ["git", "rev-parse", "branch-b"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self._git(repo, "checkout", "main")
        # Genuine merge of one head to get a real, valid MERGE_HEAD entry,
        # then simulate the octopus multi-parent format by appending a
        # second real, non-ancestor commit SHA on its own line.
        self._git(repo, "merge", "--no-ff", "--no-commit", "branch-a")
        (repo / ".git" / "MERGE_HEAD").write_text(
            f"{branch_a_sha}\n{branch_b_sha}\n", encoding="utf-8"
        )

        result = self._run(payload_cwd=repo)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

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

    def test_block_message_explains_stop_fires_every_turn(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        result = self._run(payload_cwd=repo)

        self.assertIn("end of every turn", result.stderr)

    # --- Block-message throttling (bento-neng): condense identical repeats ---

    def test_block_message_condensed_on_repeated_identical_state(self) -> None:
        # Same session, same dirty state, two consecutive Stop fires: the
        # second must still block (exit 2) but must not repeat the full
        # explanatory text -- that's the "nags every turn" complaint.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        first = self._run(payload_cwd=repo, session_id="sess-condense-1")
        second = self._run(payload_cwd=repo, session_id="sess-condense-1")

        self.assertEqual(first.returncode, 2, msg=first.stderr)
        self.assertIn("end of every turn", first.stderr)
        self.assertEqual(second.returncode, 2, msg=second.stderr)
        self.assertIn("uncommitted changes", second.stderr)
        self.assertNotIn("end of every turn", second.stderr)

    def test_block_message_condensed_persists_as_unpushed_count_climbs(self) -> None:
        # The real-world case (bento-neng): the agent keeps committing without
        # pushing, so the unpushed count changes every turn even though the
        # *kind* of problem (still unpushed, nothing new) has not. That must
        # still condense rather than re-emitting the full message solely
        # because the count ticked up.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("v2\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "second")

        first = self._run(payload_cwd=repo, session_id="sess-climb-1")

        (repo / "README.md").write_text("v3\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "third")

        second = self._run(payload_cwd=repo, session_id="sess-climb-1")

        self.assertEqual(first.returncode, 2, msg=first.stderr)
        self.assertIn("1 unpushed commit", first.stderr)
        self.assertIn("end of every turn", first.stderr)

        self.assertEqual(second.returncode, 2, msg=second.stderr)
        self.assertIn("2 unpushed commits", second.stderr)
        self.assertNotIn("end of every turn", second.stderr)

    def test_block_message_full_again_when_problem_kind_changes(self) -> None:
        # First turn: only unpushed commits. Second turn: the tree also goes
        # dirty. The problem shape changed, so the full message must return
        # rather than staying condensed.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("v2\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "second")

        first = self._run(payload_cwd=repo, session_id="sess-kind-change-1")

        (repo / "README.md").write_text("uncommitted\n", encoding="utf-8")

        second = self._run(payload_cwd=repo, session_id="sess-kind-change-1")

        self.assertEqual(first.returncode, 2, msg=first.stderr)
        self.assertEqual(second.returncode, 2, msg=second.stderr)
        self.assertIn("uncommitted changes", second.stderr)
        self.assertIn("end of every turn", second.stderr)

    def test_block_message_never_condensed_without_session_id(self) -> None:
        # Without a session_id there is nowhere safe to persist "already
        # shown this state" -- fail toward always showing the full message
        # rather than silently condensing forever.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        first = self._run(payload_cwd=repo)
        second = self._run(payload_cwd=repo)

        self.assertEqual(first.returncode, 2, msg=first.stderr)
        self.assertEqual(second.returncode, 2, msg=second.stderr)
        self.assertIn("end of every turn", first.stderr)
        self.assertIn("end of every turn", second.stderr)

    def test_block_message_full_again_in_a_fresh_session(self) -> None:
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        self._run(payload_cwd=repo, session_id="sess-fresh-a")
        second = self._run(payload_cwd=repo, session_id="sess-fresh-b")

        self.assertEqual(second.returncode, 2, msg=second.stderr)
        self.assertIn("end of every turn", second.stderr)

    def test_block_message_condensed_held_turn_does_not_count_as_shown(self) -> None:
        # A one-turn hold suppresses the block entirely (exit 0). That turn
        # must not be recorded as "the full message was already shown" --
        # the next real block afterward must still be the full message.
        repo = self._init_repo()
        self._add_remote(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")
        session_id = "sess-hold-then-block"
        self._grant_one_turn_hold(session_id)

        held = self._run(payload_cwd=repo, session_id=session_id)
        after_hold = self._run(payload_cwd=repo, session_id=session_id)

        self.assertEqual(held.returncode, 0, msg=held.stderr)
        self.assertEqual(after_hold.returncode, 2, msg=after_hold.stderr)
        self.assertIn("end of every turn", after_hold.stderr)

    def test_block_message_full_again_after_resolving_and_recurring(self) -> None:
        # Code review (bento-neng): a resolved-then-recurring problem must not
        # be conflated with the earlier, already-resolved occurrence just
        # because the recorded kind set happens to match again.
        repo = self._init_repo()
        self._add_remote(repo)
        session_id = "sess-resolve-then-recur"
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")

        first = self._run(payload_cwd=repo, session_id=session_id)

        self._git(repo, "commit", "-aqm", "resolve")
        self._git(repo, "push", "-q")
        clean = self._run(payload_cwd=repo, session_id=session_id)

        (repo / "README.md").write_text("dirty-again\n", encoding="utf-8")
        recurred = self._run(payload_cwd=repo, session_id=session_id)

        self.assertEqual(first.returncode, 2, msg=first.stderr)
        self.assertIn("end of every turn", first.stderr)

        self.assertEqual(clean.returncode, 0, msg=clean.stderr)
        self.assertEqual(clean.stderr, "")

        self.assertEqual(recurred.returncode, 2, msg=recurred.stderr)
        self.assertIn("end of every turn", recurred.stderr)

    # --- Advisory: pushed but not landed (bento-rdtn.11), exit 0 always ---

    def _pushed_unlanded_feature_branch(self) -> Path:
        """A clean, fully-pushed feature branch checked out from main, ahead
        of origin/main by one unmerged commit -- the exact "parked" shape the
        advisory targets."""
        repo = self._init_repo(branch="main")
        self._add_remote(repo, branch="main")
        self._git(repo, "checkout", "-b", "feature-y")
        (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
        self._git(repo, "add", "feature.txt")
        self._git(repo, "commit", "-qm", "feature work")
        self._git(repo, "push", "-q", "-u", "origin", "feature-y")
        return repo

    def test_advises_pushed_but_unlanded_branch(self) -> None:
        repo = self._pushed_unlanded_feature_branch()

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("'feature-y' is pushed but not landed on 'main'", result.stderr)
        self.assertIn("bento:land-work", result.stderr)
        self.assertIn("bento:closure", result.stderr)

    def test_never_advises_on_primary_branch(self) -> None:
        repo = self._init_repo(branch="main")
        self._add_remote(repo, branch="main")

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_never_advises_on_detached_head(self) -> None:
        repo = self._pushed_unlanded_feature_branch()
        self._git(repo, "checkout", "--detach", "HEAD")

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_never_advises_when_unpushed_commits_present(self) -> None:
        # The blocking case (unpushed commits) already covers this branch;
        # the advisory is for the fully-pushed, otherwise-silent case only.
        repo = self._pushed_unlanded_feature_branch()
        (repo / "feature.txt").write_text("more\n", encoding="utf-8")
        self._git(repo, "commit", "-aqm", "unpushed follow-up")

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("unpushed", result.stderr)
        self.assertNotIn("pushed but not landed", result.stderr)

    def test_never_advises_when_dirty(self) -> None:
        repo = self._pushed_unlanded_feature_branch()
        (repo / "feature.txt").write_text("dirty\n", encoding="utf-8")

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertNotIn("pushed but not landed", result.stderr)

    def test_never_advises_once_landed(self) -> None:
        repo = self._pushed_unlanded_feature_branch()
        self._git(repo, "checkout", "main")
        self._git(repo, "merge", "--no-ff", "-q", "-m", "merge feature-y", "feature-y")
        self._git(repo, "push", "-q")
        self._git(repo, "checkout", "feature-y")
        self._git(repo, "fetch", "-q", "origin")

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_never_advises_after_squash_merge(self) -> None:
        # Code review: a squash merge (e.g. GitHub's default "Squash and
        # merge") lands the branch's content under a brand-new commit SHA on
        # primary, so HEAD is never an ancestor of origin/main even though
        # the work is genuinely landed. `git merge-base --is-ancestor` alone
        # would misreport this as still-unlanded forever.
        repo = self._pushed_unlanded_feature_branch()
        self._git(repo, "checkout", "main")
        self._git(repo, "merge", "--squash", "-q", "feature-y")
        self._git(repo, "commit", "-qm", "squash-merge feature-y")
        self._git(repo, "push", "-q")
        self._git(repo, "checkout", "feature-y")
        self._git(repo, "fetch", "-q", "origin")

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_advisory_suppressed_by_require_landed_false(self) -> None:
        repo = self._pushed_unlanded_feature_branch()
        (repo / ".agent-mode.local").write_text("require_landed=false\n", encoding="utf-8")

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_advisory_throttled_to_once_per_session(self) -> None:
        repo = self._pushed_unlanded_feature_branch()

        first = self._run(payload_cwd=repo, session_id="sess-throttle")
        second = self._run(payload_cwd=repo, session_id="sess-throttle")

        self.assertIn("pushed but not landed", first.stderr)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(second.stderr, "")

    def test_advisory_repeats_in_a_fresh_session(self) -> None:
        repo = self._pushed_unlanded_feature_branch()

        self._run(payload_cwd=repo, session_id="sess-a")
        second = self._run(payload_cwd=repo, session_id="sess-b")

        self.assertIn("pushed but not landed", second.stderr)

    def test_advisory_not_throttled_across_different_branches(self) -> None:
        repo = self._pushed_unlanded_feature_branch()
        self._git(repo, "checkout", "main")
        self._git(repo, "checkout", "-b", "feature-z")
        (repo / "other.txt").write_text("other\n", encoding="utf-8")
        self._git(repo, "add", "other.txt")
        self._git(repo, "commit", "-qm", "other feature work")
        self._git(repo, "push", "-q", "-u", "origin", "feature-z")

        self._git(repo, "checkout", "feature-y")
        first = self._run(payload_cwd=repo, session_id="sess-multi")
        self._git(repo, "checkout", "feature-z")
        second = self._run(payload_cwd=repo, session_id="sess-multi")

        self.assertIn("pushed but not landed", first.stderr)
        self.assertIn("pushed but not landed", second.stderr)

    def test_never_advises_no_upstream_feature_branch(self) -> None:
        repo = self._init_repo(branch="feature-x")

        result = self._run(payload_cwd=repo, session_id="sess-1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")

    def test_never_advises_land_work_preview_worktree(self) -> None:
        repo = self._pushed_unlanded_feature_branch()
        preview_dir = self.root / "land-work-preview-abc123"
        self._git(repo, "worktree", "add", "--detach", str(preview_dir), "feature-y")

        result = self._run(payload_cwd=preview_dir, session_id="sess-1")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
