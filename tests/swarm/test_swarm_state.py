import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-state.py"
STATE_ROOT = REPO_ROOT / ".agent-state" / "swarm" / "codex"


class SwarmStateTest(unittest.TestCase):
    def run_state(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        check: bool = True,
        cwd: Path | None = None,
    ):
        return subprocess.run(
            [str(SCRIPT), *args],
            cwd=cwd or REPO_ROOT,
            check=check,
            capture_output=True,
            text=True,
            env=env or os.environ.copy(),
        )

    def test_codex_state_uses_thread_id_from_environment(self) -> None:
        thread_id = "019d-thread-from-env"
        env = os.environ.copy()
        env["CODEX_THREAD_ID"] = thread_id

        result = self.run_state("--runtime", "codex", env=env)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["thread_id"], thread_id)
        self.assertEqual(payload["checkout_root"], str(REPO_ROOT))
        self.assertEqual(payload["state_root"], str(STATE_ROOT / thread_id))
        self.assertEqual(payload["continue_file"], str(STATE_ROOT / thread_id / "continue.txt"))
        self.assertEqual(payload["handoff_file"], str(STATE_ROOT / thread_id / "handoff.md"))
        self.assertTrue(payload["ephemeral"])
        self.assertFalse(payload["state_found"])
        self.assertTrue(payload["recompute_required"])

    def test_codex_state_accepts_explicit_thread_id_override(self) -> None:
        result = self.run_state("--runtime", "codex", "--thread-id", "override-thread")
        payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["thread_id"], "override-thread")
        self.assertEqual(payload["state_root"], str(STATE_ROOT / "override-thread"))

    def test_codex_state_reports_existing_repo_state(self) -> None:
        thread_id = "existing-thread"
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_repo = Path(temp_dir_name) / "repo"
            temp_repo.mkdir()
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=temp_repo,
                check=True,
                capture_output=True,
                text=True,
            )
            state_root = temp_repo / ".agent-state" / "swarm" / "codex" / thread_id
            state_root.mkdir(parents=True, exist_ok=True)
            result = self.run_state(
                "--runtime",
                "codex",
                "--thread-id",
                thread_id,
                cwd=temp_repo,
            )
            payload = json.loads(result.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["checkout_root"], str(temp_repo))
        self.assertEqual(payload["state_root"], str(state_root))
        self.assertTrue(payload["state_found"])
        self.assertFalse(payload["recompute_required"])

    def test_codex_state_requires_thread_id(self) -> None:
        env = os.environ.copy()
        env.pop("CODEX_THREAD_ID", None)

        result = self.run_state("--runtime", "codex", env=env, check=False)
        payload = json.loads(result.stdout)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("CODEX_THREAD_ID is required", payload["error"])


if __name__ == "__main__":
    unittest.main()
