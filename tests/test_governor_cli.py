"""Boundary tests for the installed-contract CLI source entrypoint."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "governor" / "bin" / "bento-governor-v1"


class GovernorCliTest(unittest.TestCase):
    def invoke(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(ENTRYPOINT), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_help_lists_versioned_run_and_inspection_commands(self) -> None:
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run", result.stdout)
        self.assertIn("signals", result.stdout)
        self.assertIn("events", result.stdout)

    def test_run_rejects_missing_command_without_spawning(self) -> None:
        result = self.invoke("run", "--repo", "bento", "--label", "smoke", "--")
        self.assertEqual(result.returncode, 64, result.stderr)
        self.assertIn("invalid-args", result.stderr)

    def test_version_identifies_contract_major(self) -> None:
        result = self.invoke("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("contract=1", result.stdout)


if __name__ == "__main__":
    unittest.main()
