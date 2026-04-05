import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_SCRIPT = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-state.py"
CODEX_TIMEOUT_SECONDS = 45


def parse_thread_started(output: str) -> str | None:
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "thread.started":
            return payload.get("thread_id")
    return None


@unittest.skipUnless(
    os.environ.get("RUN_CODEX_INTEGRATION") == "1",
    "set RUN_CODEX_INTEGRATION=1 to run Codex CLI integration tests",
)
class SwarmCodexIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("codex") is None:
            self.skipTest("codex CLI not installed")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_file = Path(self.temp_dir.name) / "last-message.txt"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_codex(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["codex", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=CODEX_TIMEOUT_SECONDS,
        )

    def test_codex_exec_resume_preserves_thread_id_and_state_root(self) -> None:
        first = self.run_codex(
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--output-last-message",
            str(self.output_file),
            "Reply with the value of CODEX_THREAD_ID only.",
        )
        thread_id = parse_thread_started(first.stdout)
        self.assertIsNotNone(thread_id, first.stdout)

        state_payload = json.loads(
            subprocess.run(
                [str(STATE_SCRIPT), "--runtime", "codex", "--thread-id", thread_id],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        self.assertEqual(state_payload["state_root"], f"/tmp/codex-swarm/{thread_id}")

        resumed = self.run_codex(
            "exec",
            "--json",
            "--skip-git-repo-check",
            "resume",
            thread_id,
            "Reply with the value of CODEX_THREAD_ID only.",
        )
        resumed_thread_id = parse_thread_started(resumed.stdout)
        self.assertEqual(resumed_thread_id, thread_id, resumed.stdout)


if __name__ == "__main__":
    unittest.main()
