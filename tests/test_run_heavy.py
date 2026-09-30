import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_HEAVY = REPO_ROOT / "catalog" / "skills" / "launch-work" / "scripts" / "run-heavy"


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


class RunHeavyShimTest(unittest.TestCase):
    """run-heavy is a fail-closed shim over the installed governor (contract v1)."""

    def fake_governor(self, body: str) -> str:
        import tempfile

        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        path = Path(directory) / "bento-governor-v1"
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)
        return str(path)

    def test_script_is_executable(self) -> None:
        import os

        self.assertTrue(os.access(RUN_HEAVY, os.X_OK), "run-heavy must be executable")

    def test_no_args_prints_usage_and_exits_64(self) -> None:
        result = run_heavy()
        self.assertEqual(result.returncode, 64)
        self.assertIn("usage:", result.stderr)

    def test_missing_governor_fails_closed_without_running_command(self) -> None:
        result = run_heavy("echo", "ran", env_overrides={"BENTO_GOVERNOR_BIN": "/nonexistent/governor"})
        self.assertEqual(result.returncode, 70)
        self.assertNotIn("ran", result.stdout)

    def test_delegates_with_default_repo_label_and_explicit_weight(self) -> None:
        fake = self.fake_governor('printf "%s\\n" "$@"\n')
        result = run_heavy("--weight", "3", "echo", "hi", env_overrides={"BENTO_GOVERNOR_BIN": fake})
        self.assertEqual(result.returncode, 0, result.stderr)
        args = result.stdout.split()
        self.assertEqual(args[:2], ["run", "--weight"])
        self.assertEqual(args[2], "3")
        self.assertIn("--label", args)
        self.assertEqual(args[args.index("--") + 1 :], ["echo", "hi"])

    def test_propagates_governor_exit_status_and_ignores_heavy_max_wait(self) -> None:
        fake = self.fake_governor("exit 69\n")
        result = run_heavy(
            "echo", "ran",
            env_overrides={"BENTO_GOVERNOR_BIN": fake, "HEAVY_MAX_WAIT": "0"},
        )
        self.assertEqual(result.returncode, 69)
        self.assertIn("HEAVY_MAX_WAIT is ignored", result.stderr)
        self.assertNotIn("proceeding anyway", result.stderr)


if __name__ == "__main__":
    unittest.main()
