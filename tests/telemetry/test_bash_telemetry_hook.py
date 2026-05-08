import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "catalog" / "hooks" / "telemetry" / "scripts" / "record-bash.py"


def load_hook():
    loader = importlib.machinery.SourceFileLoader("record_bash", str(HOOK))
    spec = importlib.util.spec_from_loader("record_bash", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CommandParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hook = load_hook()
        self.script = "/repo/catalog/skills/land-work/scripts/land-work-prepare.py"

    def test_direct_helper_call(self) -> None:
        parsed = self.hook.parse_bash_command(f"{self.script} --base main", cwd="/tmp")
        self.assertEqual(parsed.argv, [self.script, "--base", "main"])
        self.assertEqual(parsed.realpath, self.script)

    def test_rtk_wrapped_helper_call(self) -> None:
        parsed = self.hook.parse_bash_command(f"rtk {self.script} --base main", cwd="/tmp")
        self.assertEqual(parsed.argv, [self.script, "--base", "main"])

    def test_python_wrapped_helper_call(self) -> None:
        parsed = self.hook.parse_bash_command(f"python3 {self.script} --base main", cwd="/tmp")
        self.assertEqual(parsed.argv, [self.script, "--base", "main"])

    def test_rtk_python_wrapped_helper_call(self) -> None:
        parsed = self.hook.parse_bash_command(f"rtk python3 {self.script} --base main", cwd="/tmp")
        self.assertEqual(parsed.argv, [self.script, "--base", "main"])

    def test_relative_helper_uses_cwd_for_realpath(self) -> None:
        parsed = self.hook.parse_bash_command(
            "catalog/skills/swarm/scripts/swarm-triage.py --json",
            cwd="/repo",
        )
        self.assertEqual(parsed.realpath, "/repo/catalog/skills/swarm/scripts/swarm-triage.py")

    def test_unrelated_command_returns_none(self) -> None:
        self.assertIsNone(self.hook.parse_bash_command("git status --short", cwd="/repo"))

    def test_malformed_command_returns_none(self) -> None:
        self.assertIsNone(self.hook.parse_bash_command("python3 'unterminated", cwd="/repo"))


class PayloadParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hook = load_hook()

    def test_payload_extracts_exit_stderr_interrupted_and_duration(self) -> None:
        payload = {
            "session_id": "s1",
            "tool_input": {"command": "echo hi", "cwd": "/repo"},
            "tool_response": {
                "exit_code": 2,
                "stderr": "boom",
                "interrupted": True,
                "duration_ms": 51,
            },
        }
        event = self.hook.event_from_payload(payload)
        self.assertEqual(event.command, "echo hi")
        self.assertEqual(event.cwd, "/repo")
        self.assertEqual(event.exit_code, 2)
        self.assertEqual(event.stderr, "boom")
        self.assertTrue(event.interrupted)
        self.assertEqual(event.duration_ms, 51)
        self.assertEqual(event.session_id, "s1")


class HookMainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        self.env = {
            **os.environ,
            "XDG_STATE_HOME": str(self.state),
            "HOME": str(self.home),
            "BENTO_TELEMETRY_NOW": "2026-04-26T12:00:00Z",
        }
        self.script = str(REPO_ROOT / "catalog" / "skills" / "land-work" / "scripts" / "land-work-prepare.py")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_hook(self, payload: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def records(self) -> list[dict]:
        path = self.state / "bento" / "telemetry" / "2026-04-26.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_success_record(self) -> None:
        result = self.run_hook(
            {
                "session_id": "s1",
                "tool_input": {"command": f"{self.script} --base main"},
                "tool_response": {"exit_code": 0, "stderr": "", "duration_ms": 10},
            }
        )
        self.assertEqual(result.returncode, 0)
        rec = self.records()[0]
        self.assertEqual(rec["class"], "ok")
        self.assertEqual(rec["skill"], "land-work")
        self.assertEqual(rec["script"], "land-work-prepare.py")
        self.assertEqual(rec["argv_redacted"], ["--base", "main"])

    def test_runtime_error_record(self) -> None:
        result = self.run_hook(
            {
                "session_id": "s1",
                "tool_input": {"command": f"{self.script} --base main"},
                "tool_response": {"exit_code": 1, "stderr": "Traceback\nValueError"},
            }
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.records()[0]["class"], "error")

    def test_interrupted_record(self) -> None:
        result = self.run_hook(
            {
                "session_id": "s1",
                "tool_input": {"command": f"{self.script} --base main"},
                "tool_response": {"exit_code": 0, "stderr": "", "interrupted": True},
            }
        )
        self.assertEqual(result.returncode, 0)
        rec = self.records()[0]
        self.assertEqual(rec["class"], "error")
        self.assertTrue(rec["interrupted"])

    def test_not_found_record(self) -> None:
        result = self.run_hook(
            {
                "session_id": "s1",
                "tool_input": {"command": f"{self.script} --base main"},
                "tool_response": {
                    "exit_code": 127,
                    "stderr": f"bash: {self.script}: No such file or directory",
                },
            }
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.records()[0]["class"], "not_found")

    def test_unrelated_command_writes_no_record(self) -> None:
        result = self.run_hook(
            {
                "session_id": "s1",
                "tool_input": {"command": "git status"},
                "tool_response": {"exit_code": 0, "stderr": ""},
            }
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.records(), [])

    def test_malformed_payload_exits_zero_without_record(self) -> None:
        result = subprocess.run(
            ["python3", str(HOOK)],
            input="{not json",
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.records(), [])

    def test_hook_internal_error_is_logged_without_raising(self) -> None:
        self.env["BENTO_TELEMETRY_FORCE_APPEND_ERROR"] = "1"
        result = self.run_hook(
            {
                "session_id": "s1",
                "tool_input": {"command": f"{self.script} --base main"},
                "tool_response": {"exit_code": 0, "stderr": ""},
            }
        )
        self.assertEqual(result.returncode, 0)
        errors = self.state / "bento" / "telemetry" / "hook-errors.log"
        self.assertIn("forced append error", errors.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
