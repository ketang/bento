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


class CliDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        # Isolate XDG so user-installed extensions don't leak in.
        self.env = os.environ.copy()
        self.env["XDG_CONFIG_HOME"] = str(self.root / "xdg-empty")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_discover_emits_json_with_files_and_warnings(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hooks/pre"
        _write(d / "10-first.sh", executable=True)
        _write(d / "no-prefix.sh", executable=True)

        result = subprocess.run(
            [
                str(CLI),
                "discover",
                "--repo-root",
                str(self.repo),
                "--skill",
                "launch-work",
                "--kind",
                "hooks",
                "--position",
                "pre",
            ],
            capture_output=True,
            text=True,
            env=self.env,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(
            [Path(p).name for p in payload["files"]],
            ["10-first.sh"],
        )
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertIn("no-prefix.sh", payload["warnings"][0])
