import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_SCRIPT = REPO_ROOT / "catalog" / "skills" / "handoff" / "scripts" / "handoff.py"


class HandoffHelpTest(unittest.TestCase):
    def test_help_flag_exits_zero_and_describes_inputs(self) -> None:
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--input", result.stdout)
        self.assertIn("--slug", result.stdout)
        self.assertIn("--verbose", result.stdout)


if __name__ == "__main__":
    unittest.main()
