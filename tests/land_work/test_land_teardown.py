"""bento-c96u.16: `land.py --teardown-only` (land-work step 10) and the residue matcher."""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.land_work.test_land_driver import LAND_SCRIPT, REPO_ROOT, LandDriverTestBase
from tests.script_test_utils import git, load_script_module_with_git_state

DOCTOR = REPO_ROOT / "catalog/hooks/bento/claude/scripts/agent-env-doctor.py"
CODEX_DOCTOR = REPO_ROOT / "catalog/hooks/bento/codex/scripts/agent-env-doctor.py"


def load(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TeardownTest(LandDriverTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.hook_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.hook_dir.cleanup)

    def land(self) -> None:
        result = self.run_driver()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("teardown", json.loads(result.stdout))
        self.assertTrue(self.worktree.exists(), "a plain landing must leave the worktree for steps 8a-9b")

    def teardown(self, *args: str, cwd: Path | None = None, hook: str | None = None) -> tuple[subprocess.CompletedProcess, dict]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("BENTO_LAND_")}
        env["BENTO_LAND_TEST_RESIDUE_WAIT"] = "0"
        env["XDG_CONFIG_HOME"] = str(Path(self.hook_dir.name) / "xdg")
        if hook:
            script = Path(self.hook_dir.name) / "hook.sh"
            script.write_text(f"#!/usr/bin/env bash\n{hook}\n", encoding="utf-8")
            script.chmod(0o755)
            env["BENTO_LAND_TEST_AFTER_REMOVE"] = str(script)
        result = subprocess.run(
            [str(LAND_SCRIPT), "--teardown-only", *args], cwd=cwd or self.worktree, capture_output=True,
            text=True, env=env, check=False, stdin=subprocess.DEVNULL,
        )
        return result, json.loads(result.stdout)

    def branches(self) -> list[str]:
        return git(self.repo, "branch", "--list", "--format=%(refname:short)", "feature/test").stdout.split()

    def assert_kept(self, result, payload, reason: str) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], "skipped")
        self.assertIn(reason, payload["reason"])
        self.assertTrue(self.worktree.exists())
        self.assertEqual(self.branches(), ["feature/test"])

    def test_landed_worktree_and_branch_are_removed(self) -> None:
        self.land()
        result, payload = self.teardown()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], "removed")
        self.assertTrue(payload["branch_deleted"])
        self.assertEqual(payload["branch"], "feature/test")
        self.assertEqual(payload["worktree"], str(self.worktree.resolve()))
        self.assertEqual(payload["cd"], str(self.repo.resolve()))
        self.assertFalse(self.worktree.exists())
        self.assertEqual(self.branches(), [])
        self.assertNotIn(str(self.worktree), git(self.repo, "worktree", "list").stdout)

    def test_worktree_arg_from_another_cwd(self) -> None:
        self.land()
        result, payload = self.teardown("--worktree", str(self.worktree), "--branch", "feature/test", cwd=self.repo)
        self.assertEqual(payload["status"], "removed", result.stderr)
        self.assertFalse(self.worktree.exists())

    def test_branch_assertion_mismatch_skips(self) -> None:
        self.land()
        result, payload = self.teardown("--branch", "other")
        self.assert_kept(result, payload, "not other")

    def test_unlanded_branch_is_refused(self) -> None:
        result, payload = self.teardown()
        self.assert_kept(result, payload, "not landed")

    def test_primary_checkout_is_refused(self) -> None:
        self.land()
        result, payload = self.teardown(cwd=self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], "skipped")
        self.assertTrue(self.repo.exists() and self.worktree.exists())

    def test_untracked_file_is_refused(self) -> None:
        self.land()
        (self.worktree / "scratch.txt").write_text("keep\n", encoding="utf-8")
        result, payload = self.teardown()
        self.assert_kept(result, payload, "scratch.txt")
        self.assertTrue((self.worktree / "scratch.txt").exists())

    def test_modified_tracked_file_is_refused(self) -> None:
        self.land()
        (self.worktree / "feature.txt").write_text("changed\n", encoding="utf-8")
        result, payload = self.teardown()
        self.assert_kept(result, payload, "feature.txt")

    def test_ignored_precious_file_is_refused_but_target_is_fine(self) -> None:
        (self.worktree / ".gitignore").write_text(".env\ntarget/\n", encoding="utf-8")
        git(self.worktree, "add", ".gitignore")
        git(self.worktree, "commit", "-m", "ignore")
        self.land()
        (self.worktree / "target").mkdir()
        (self.worktree / "target" / "artifact").write_text("x", encoding="utf-8")
        (self.worktree / ".env").write_text("SECRET=1\n", encoding="utf-8")
        result, payload = self.teardown()
        self.assert_kept(result, payload, ".env")
        (self.worktree / ".env").unlink()
        result, payload = self.teardown()
        self.assertEqual(payload["status"], "removed", result.stderr)

    def test_ignored_file_next_to_custom_glob_is_refused(self) -> None:
        (self.worktree / ".gitignore").write_text("build/\n", encoding="utf-8")
        git(self.worktree, "add", ".gitignore")
        git(self.worktree, "commit", "-m", "ignore")
        self.commit_globs("build/gen/**\n")
        self.land()
        (self.worktree / "build" / "gen").mkdir(parents=True)
        (self.worktree / "build" / "gen" / "a").write_text("x", encoding="utf-8")
        (self.worktree / "build" / "local.env").write_text("SECRET=1\n", encoding="utf-8")
        result, payload = self.teardown()
        self.assert_kept(result, payload, "build/local.env")
        (self.worktree / "build" / "local.env").unlink()
        result, payload = self.teardown()
        self.assertEqual(payload["status"], "removed", result.stderr)

    def test_non_repo_worktree_is_reported_not_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, payload = self.teardown("--worktree", tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(payload["status"], ("skipped", "error"))
        self.assertTrue(payload.get("reason") or payload.get("warning"))

    def test_missing_origin_ref_is_reported(self) -> None:
        self.land()
        git(self.repo, "remote", "remove", "origin")
        result, payload = self.teardown()
        self.assert_kept(result, payload, "origin/main")

    def test_locked_worktree_is_refused(self) -> None:
        self.land()
        git(self.repo, "worktree", "lock", str(self.worktree))
        result, payload = self.teardown()
        self.assert_kept(result, payload, "refused")

    def test_branch_delete_failure_is_a_warning(self) -> None:
        self.land()
        # Primary's local main no longer contains the feature: `branch -d`
        # refuses, but origin/main (the real guard) does.
        git(self.repo, "reset", "--hard", "HEAD~1")
        result, payload = self.teardown()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["status"], "removed")
        self.assertFalse(payload["branch_deleted"])
        self.assertIn("branch -d", payload["warning"])
        self.assertFalse(self.worktree.exists())
        self.assertEqual(self.branches(), ["feature/test"])

    def test_malformed_wait_env_does_not_crash(self) -> None:
        self.land()
        env = {k: v for k, v in os.environ.items() if not k.startswith("BENTO_LAND_")}
        env["BENTO_LAND_TEST_RESIDUE_WAIT"] = "soon"
        env["XDG_CONFIG_HOME"] = self.hook_dir.name
        # Wait falls back to the 2s default; only assert it still succeeds.
        result = subprocess.run(
            [str(LAND_SCRIPT), "--teardown-only"], cwd=self.worktree, capture_output=True, text=True,
            env=env, check=False, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(json.loads(result.stdout)["status"], "removed", result.stderr)

    # -- residue sweep -------------------------------------------------------- #

    def test_residue_only_leftover_is_swept(self) -> None:
        self.land()
        result, payload = self.teardown(
            hook='mkdir -p "$1/target/flycheck0" && : > "$1/target/flycheck0/stdout" && : > "$1/target/flycheck0/stderr"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["residue_removed"])
        self.assertEqual(payload["residue_left"], [])
        self.assertFalse(self.worktree.exists())

    def test_leftover_with_real_files_is_kept(self) -> None:
        self.land()
        result, payload = self.teardown(
            hook='mkdir -p "$1/src" "$1/target/flycheck0" && echo x > "$1/src/x.rs" && : > "$1/target/flycheck0/stdout"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(payload["residue_removed"])
        self.assertIn("src/x.rs", payload["residue_left"])
        self.assertTrue((self.worktree / "src" / "x.rs").exists())

    def commit_globs(self, text: str) -> None:
        path = self.repo / ".agent-plugins/bento/bento/land-work/residue-globs.txt"
        path.write_text(text, encoding="utf-8")
        git(self.repo, "add", str(path.relative_to(self.repo)))
        git(self.repo, "commit", "-m", "residue globs")
        git(self.repo, "push", "origin", "main")
        git(self.worktree, "rebase", "main")

    def test_repo_scope_globs_extend_the_allowlist(self) -> None:
        self.commit_globs("# extra\n.idea/**\n")
        self.land()
        result, payload = self.teardown(hook='mkdir -p "$1/.idea" && : > "$1/.idea/workspace.xml"')
        self.assertTrue(payload["residue_removed"], result.stderr)

    def test_home_scope_globs_extend_the_allowlist(self) -> None:
        xdg = Path(self.hook_dir.name) / "xdg" / "agent-plugins/bento/bento/land-work"
        xdg.mkdir(parents=True)
        (xdg / "residue-globs.txt").write_text(".idea/**\n", encoding="utf-8")
        self.land()
        result, payload = self.teardown(hook='mkdir -p "$1/.idea" && : > "$1/.idea/workspace.xml"')
        self.assertTrue(payload["residue_removed"], result.stderr)

    def test_widening_globs_from_the_repo_are_rejected(self) -> None:
        self.commit_globs("**\n*\n../x/**\n\n")
        self.land()
        result, payload = self.teardown(hook='mkdir -p "$1/src" && echo x > "$1/src/x.rs"')
        self.assertFalse(payload["residue_removed"])
        self.assertIn("src/x.rs", payload["residue_left"])


class ResidueMatcherParityTest(unittest.TestCase):
    """land.py and both doctors must classify the same paths identically."""

    GLOBS = [
        "target/flycheck*/**", ".idea/**", "**", "*", "../x/**", "", "a/b*c/**", "/abs/**", "tmp/*.log",
    ]
    PATHS = [
        "target/flycheck0/stdout", "target/flycheck12/a/b", "target/debug/x", "src/x.rs",
        ".idea/workspace.xml", "other/file", "a/bxc/z", "a/bc/z", "tmp/a.log", "tmp/d/a.log", "abs/x",
    ]

    def test_same_table_same_answers(self) -> None:
        land = load_script_module_with_git_state("land_under_test", LAND_SCRIPT)
        doctors = [load("doctor_claude", DOCTOR), load("doctor_codex", CODEX_DOCTOR)]
        with tempfile.TemporaryDirectory() as tmp:
            root, home = Path(tmp) / "root", Path(tmp) / "home"
            (root / ".agent-plugins/bento/bento/land-work").mkdir(parents=True)
            (root / ".agent-plugins/bento/bento/land-work/residue-globs.txt").write_text(
                "\n".join(self.GLOBS) + "\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home / ".config")}):
                land_patterns = land.residue_regexes(land.residue_globs(root))
                expected = [any(p.match(path) for p in land_patterns) for path in self.PATHS]
                for doctor in doctors:
                    patterns = doctor._residue_regexes(root, home)
                    self.assertEqual([any(p.match(path) for p in patterns) for path in self.PATHS], expected)
        self.assertEqual(
            dict(zip(self.PATHS, expected)),
            {
                "target/flycheck0/stdout": True, "target/flycheck12/a/b": True, "target/debug/x": False,
                "src/x.rs": False, ".idea/workspace.xml": True, "other/file": False, "a/bxc/z": True,
                "a/bc/z": True, "tmp/a.log": True, "tmp/d/a.log": False, "abs/x": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
