import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_HEAVY = REPO_ROOT / "scripts" / "run-heavy"

# run-heavy depends on Linux-only facilities (/proc/loadavg) and util-linux's
# ionice. Skip the whole module cleanly where those are unavailable.
_MISSING = [
    tool for tool in ("nice", "ionice", "nproc") if shutil.which(tool) is None
]
_SKIP_REASON = (
    "run-heavy requires Linux /proc/loadavg and " + ", ".join(_MISSING)
    if _MISSING or not Path("/proc/loadavg").exists()
    else ""
)


def run_heavy(*args: str, env_overrides: dict[str, str] | None = None):
    import os

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(RUN_HEAVY), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@unittest.skipIf(_SKIP_REASON, _SKIP_REASON)
class RunHeavyTest(unittest.TestCase):
    def test_script_is_executable(self) -> None:
        self.assertTrue(RUN_HEAVY.is_file())
        import os

        self.assertTrue(os.access(RUN_HEAVY, os.X_OK), "run-heavy must be executable")

    def test_no_args_prints_usage_and_exits_nonzero(self) -> None:
        result = run_heavy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage:", result.stderr)

    def test_executes_command_when_load_below_threshold(self) -> None:
        # A huge load factor keeps the threshold well above real load, so the
        # wait loop is skipped and the command execs immediately.
        result = run_heavy(
            "printf", "%s-%s", "alpha", "beta",
            env_overrides={"HEAVY_LOAD_FACTOR": "100000"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "alpha-beta")

    def test_propagates_command_exit_code(self) -> None:
        result = run_heavy(
            "sh", "-c", "exit 7",
            env_overrides={"HEAVY_LOAD_FACTOR": "100000"},
        )
        self.assertEqual(result.returncode, 7)

    def test_proceeds_after_max_wait_deadline(self) -> None:
        # Factor 0 forces the threshold to 0 so measured load always exceeds it;
        # MAX_WAIT 0 makes the deadline fire on the first iteration, so the loop
        # breaks and execs without sleeping.
        result = run_heavy(
            "echo", "ran",
            env_overrides={"HEAVY_LOAD_FACTOR": "0", "HEAVY_MAX_WAIT": "0"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ran")
        self.assertIn("proceeding anyway", result.stderr)


if __name__ == "__main__":
    sys.exit(unittest.main())
