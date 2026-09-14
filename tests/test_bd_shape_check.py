"""Run beads-issue-flow's bd-shape-check.py against whatever `bd` is on
PATH, and confirm it does the intended thing when `bd` is absent.

Skipped (not failed) when `bd` is not on PATH: bento's own test suite runs
in environments without a beads install, and this check exists to verify a
live CLI's shapes, not to require one.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "skills"
    / "beads-issue-flow"
    / "scripts"
    / "bd-shape-check.py"
)


def _run_script(env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False, env=env
    )


class BdShapeCheckMissingBinaryTest(unittest.TestCase):
    def test_skips_cleanly_when_bd_not_on_path(self) -> None:
        # An empty PATH dir with no `bd` on it -- invoked via sys.executable
        # directly (not the script's own shebang) so the python3 interpreter
        # itself doesn't need PATH lookup to run.
        with tempfile.TemporaryDirectory() as empty_bin_dir:
            result = _run_script(env={"PATH": empty_bin_dir})
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("skipping", result.stdout.lower())


@unittest.skipUnless(shutil.which("bd"), "bd must be on PATH for the live shape check")
class BdShapeCheckLiveTest(unittest.TestCase):
    def test_documented_shapes_hold_against_installed_bd(self) -> None:
        result = _run_script()
        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "bd-shape-check.py reported a FAIL against the installed bd -- "
                "beads-issue-flow/SKILL.md's CLI shapes section and/or "
                "metadata.json's verified_bd_version pin need updating.\n"
                f"{result.stdout}{result.stderr}"
            ),
        )
        self.assertNotIn("[FAIL]", result.stdout)


if __name__ == "__main__":
    unittest.main()
