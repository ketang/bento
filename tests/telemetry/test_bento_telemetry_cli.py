import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "catalog" / "hooks" / "telemetry" / "scripts" / "bento-telemetry.py"


class BentoTelemetryCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.env = {**os.environ, "XDG_STATE_HOME": str(self.state)}
        self.store = self.state / "bento" / "telemetry"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(CLI), *args],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )

    def write_jsonl(self, day: str, lines: list[dict | str]) -> None:
        self.store.mkdir(parents=True, exist_ok=True)
        path = self.store / f"{day}.jsonl"
        rendered = [
            line if isinstance(line, str) else json.dumps(line, separators=(",", ":"))
            for line in lines
        ]
        path.write_text("\n".join(rendered) + "\n", encoding="utf-8")

    def record(
        self,
        *,
        rec_id: str,
        ts: str,
        plugin: str = "bento",
        skill: str = "land-work",
        cls: str = "ok",
        session: str = "s1",
    ) -> dict:
        return {
            "v": 1,
            "kind": "script",
            "id": rec_id,
            "ts": ts,
            "session_id": session,
            "marketplace": "bento",
            "plugin": plugin,
            "skill": skill,
            "script": "helper.py",
            "argv_redacted": [],
            "exit": 0 if cls == "ok" else 1,
            "class": cls,
            "interrupted": False,
            "duration_ms": 5,
            "stderr_tail": [],
        }

    def test_path_prints_store_directory(self) -> None:
        result = self.run_cli("path")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), str(self.store))

    def test_tail_empty_store_outputs_empty_json_array(self) -> None:
        result = self.run_cli("tail", "--json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), [])

    def test_tail_skips_corrupt_jsonl_and_sorts_by_timestamp_then_id(self) -> None:
        older = self.record(rec_id="b", ts="2026-04-25T12:00:00.000Z")
        same_time_a = self.record(rec_id="a", ts="2026-04-26T12:00:00.000Z")
        same_time_c = self.record(rec_id="c", ts="2026-04-26T12:00:00.000Z")
        self.write_jsonl("2026-04-26", [same_time_c, "{bad json", same_time_a])
        self.write_jsonl("2026-04-25", [older])

        result = self.run_cli("tail", "--json")

        self.assertEqual(result.returncode, 0)
        self.assertEqual([rec["id"] for rec in json.loads(result.stdout)], ["b", "a", "c"])

    def test_tail_filters_since_skill_plugin_class_and_session(self) -> None:
        self.write_jsonl(
            "2026-04-26",
            [
                self.record(rec_id="old", ts="2026-04-26T12:59:59.000Z"),
                self.record(rec_id="wrong-skill", ts="2026-04-26T13:00:01.000Z", skill="swarm"),
                self.record(rec_id="wrong-plugin", ts="2026-04-26T13:00:02.000Z", plugin="trackers"),
                self.record(rec_id="wrong-class", ts="2026-04-26T13:00:03.000Z", cls="error"),
                self.record(rec_id="wrong-session", ts="2026-04-26T13:00:04.000Z", session="s2"),
                self.record(rec_id="match", ts="2026-04-26T13:00:05.000Z"),
            ],
        )

        result = self.run_cli(
            "tail",
            "--json",
            "--since",
            "2026-04-26T08:00:00-05:00",
            "--skill",
            "land-work",
            "--plugin",
            "bento",
            "--class",
            "ok",
            "--session",
            "s1",
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual([rec["id"] for rec in json.loads(result.stdout)], ["match"])

    def test_summarize_empty_store_has_stable_zero_json_shape(self) -> None:
        result = self.run_cli("summarize", "--json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "total": 0,
                "by_class": {},
                "by_plugin": {},
                "by_skill": {},
                "by_day": {},
            },
        )

    def test_summarize_aggregates_multiple_days_and_filters(self) -> None:
        self.write_jsonl(
            "2026-04-25",
            [
                self.record(rec_id="a", ts="2026-04-25T23:00:00.000Z", cls="ok"),
                self.record(rec_id="b", ts="2026-04-25T23:05:00.000Z", cls="error"),
            ],
        )
        self.write_jsonl(
            "2026-04-26",
            [
                self.record(rec_id="c", ts="2026-04-26T01:00:00.000Z", cls="ok"),
                self.record(rec_id="d", ts="2026-04-26T01:05:00.000Z", skill="swarm"),
            ],
        )

        result = self.run_cli("summarize", "--json", "--skill", "land-work")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "total": 3,
                "by_class": {"error": 1, "ok": 2},
                "by_plugin": {"bento": 3},
                "by_skill": {"land-work": 3},
                "by_day": {"2026-04-25": 2, "2026-04-26": 1},
            },
        )

    def test_tail_stable_json_output_uses_sorted_keys_and_compact_lists(self) -> None:
        self.write_jsonl("2026-04-26", [self.record(rec_id="a", ts="2026-04-26T12:00:00.000Z")])

        result = self.run_cli("tail", "--json")

        self.assertEqual(result.returncode, 0)
        self.assertIn('"argv_redacted":[]', result.stdout)
        self.assertLess(result.stdout.index('"class"'), result.stdout.index('"duration_ms"'))

    def test_export_stub_returns_two(self) -> None:
        result = self.run_cli("export")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not implemented", result.stderr)


if __name__ == "__main__":
    unittest.main()
