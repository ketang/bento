import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "catalog/skills/launch-work/scripts/run-lifecycle-extensions.py"


def _write_hook(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class RunHooksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = os.environ.copy()
        self.env["XDG_CONFIG_HOME"] = str(self.root / "xdg-empty")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _base_args(self, position: str = "pre", advisory: bool = False) -> list[str]:
        args = [
            str(CLI),
            "run-hooks",
            "--repo-root",
            str(self.repo),
            "--skill",
            "launch-work",
            "--position",
            position,
            "--branch",
            "test-branch",
            "--worktree",
            str(self.repo),
            "--base-ref",
            "main",
            "--runtime",
            "claude",
        ]
        if advisory:
            args.append("--advisory")
        return args

    def test_all_hooks_pass_returns_zero(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hook-scripts/pre"
        _write_hook(d / "10-first.sh", "echo first\nexit 0\n")
        _write_hook(d / "20-second.sh", "echo second\nexit 0\n")

        result = subprocess.run(
            self._base_args(), capture_output=True, text=True, env=self.env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("first", result.stdout)
        self.assertIn("second", result.stdout)

    def test_first_failure_aborts_and_returns_exit_code(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hook-scripts/pre"
        _write_hook(d / "10-fail.sh", "echo bad\nexit 7\n")
        _write_hook(d / "20-never.sh", "echo should-not-run\nexit 0\n")

        result = subprocess.run(
            self._base_args(), capture_output=True, text=True, env=self.env
        )
        self.assertEqual(result.returncode, 7)
        self.assertIn("bad", result.stdout)
        self.assertNotIn("should-not-run", result.stdout)

    def test_human_handoff_exit_75(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hook-scripts/pre"
        _write_hook(d / "10-handoff.sh", "echo need-human\nexit 75\n")

        result = subprocess.run(
            self._base_args(), capture_output=True, text=True, env=self.env
        )
        self.assertEqual(result.returncode, 75)
        self.assertIn("need-human", result.stdout)

    def test_advisory_mode_returns_zero_on_failure(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/land-work/hook-scripts/post"
        _write_hook(d / "10-warn.sh", "echo warning\nexit 3\n")
        _write_hook(d / "20-also.sh", "echo continues\nexit 0\n")

        args = [
            str(CLI),
            "run-hooks",
            "--repo-root",
            str(self.repo),
            "--skill",
            "land-work",
            "--position",
            "post",
            "--branch",
            "feature",
            "--worktree",
            str(self.repo),
            "--advisory",
        ]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("warning", result.stdout)
        self.assertIn("continues", result.stdout)

    def test_env_vars_present_in_hook(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hook-scripts/pre"
        body = (
            "echo PHASE=$BENTO_HOOK_PHASE\n"
            "echo POSITION=$BENTO_HOOK_POSITION\n"
            "echo BRANCH=$BENTO_HOOK_BRANCH\n"
            "echo HUMAN=$BENTO_HOOK_REQUIRES_HUMAN\n"
            "exit 0\n"
        )
        _write_hook(d / "10-env.sh", body)

        result = subprocess.run(
            self._base_args(), capture_output=True, text=True, env=self.env, check=True
        )
        self.assertIn("PHASE=launch-work", result.stdout)
        self.assertIn("POSITION=pre", result.stdout)
        self.assertIn("BRANCH=test-branch", result.stdout)
        self.assertIn("HUMAN=75", result.stdout)

    def test_timeout_kills_hung_hook(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hook-scripts/pre"
        _write_hook(d / "10-hang.sh", "sleep 5\nexit 0\n")

        args = self._base_args() + ["--timeout", "1"]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 124)
        self.assertIn("TIMEOUT", result.stderr)
