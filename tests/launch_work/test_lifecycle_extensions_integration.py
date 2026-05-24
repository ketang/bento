import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "catalog/skills/launch-work/scripts/run-lifecycle-extensions.py"


def _write(path: Path, content: str = "x", executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class IntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = os.environ.copy()
        self.env["XDG_CONFIG_HOME"] = str(self.root / "xdg-empty")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pre_pass_then_actions_discoverable(self) -> None:
        # A passing pre hook
        hook_dir = self.repo / ".agent-plugins/bento/bento/launch-work/hook-scripts/pre"
        _write(
            hook_dir / "10-ok.sh",
            "#!/bin/sh\necho pre-ok\nexit 0\n",
            executable=True,
        )
        # Two prose hook skills in order
        action_dir = self.repo / ".agent-plugins/bento/bento/launch-work/hook-skills/pre"
        _write(action_dir / "10-first.md", "# First hook skill\n\n## Body\nDo X.\n")
        _write(action_dir / "20-second.md", "# Second hook skill\n\n## Body\nDo Y.\n")

        run_args = [
            str(CLI), "run-hooks",
            "--repo-root", str(self.repo),
            "--skill", "launch-work",
            "--position", "pre",
            "--branch", "test", "--worktree", str(self.repo),
        ]
        run = subprocess.run(run_args, capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 0, run.stderr)

        disc_args = [
            str(CLI), "discover",
            "--repo-root", str(self.repo),
            "--skill", "launch-work",
            "--kind", "hook-skills",
            "--position", "pre",
        ]
        disc = subprocess.run(
            disc_args, capture_output=True, text=True, env=self.env, check=True
        )
        payload = json.loads(disc.stdout)
        self.assertEqual(
            [Path(p).name for p in payload["files"]],
            ["10-first.md", "20-second.md"],
        )

    def test_post_advisory_continues_past_failure(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/land-work/hook-scripts/post"
        _write(
            d / "10-fails.sh",
            "#!/bin/sh\necho first-failed\nexit 5\n",
            executable=True,
        )
        _write(
            d / "20-runs.sh",
            "#!/bin/sh\necho second-ran\nexit 0\n",
            executable=True,
        )

        args = [
            str(CLI), "run-hooks",
            "--repo-root", str(self.repo),
            "--skill", "land-work",
            "--position", "post",
            "--advisory",
            "--branch", "feature", "--worktree", str(self.repo),
            "--landed", "1",
        ]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("first-failed", result.stdout)
        self.assertIn("second-ran", result.stdout)

    def test_no_extensions_present_returns_zero(self) -> None:
        args = [
            str(CLI), "run-hooks",
            "--repo-root", str(self.repo),
            "--skill", "launch-work",
            "--position", "pre",
            "--branch", "x", "--worktree", str(self.repo),
        ]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0)
