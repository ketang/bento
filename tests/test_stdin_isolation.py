import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class StdinIsolationTest(unittest.TestCase):
    def _run_with_open_stdin(self, *cmd: str) -> subprocess.CompletedProcess[str]:
        # stdin is an open pipe that never reaches EOF.
        holder = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdout=subprocess.PIPE,
        )
        try:
            return subprocess.run(
                [sys.executable, *cmd],
                cwd=REPO_ROOT,
                stdin=holder.stdout,
                capture_output=True,
                text=True,
                timeout=60,
            )
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()

    def test_register_hook_tests_do_not_hang_on_never_eof_stdin(self) -> None:
        proc = self._run_with_open_stdin(
            "-m", "unittest", "tests.test_register_require_worktree_hook"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_package_guard_replaces_stdin(self) -> None:
        proc = self._run_with_open_stdin(
            "-c", "import tests, sys; assert sys.stdin.read() == ''"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
