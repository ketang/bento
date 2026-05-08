"""Tests for catalog/skills/bentobug/scripts/bentobug-report.py.

Acceptance from bento-fmx.2:
  1. explicit target — record verbatim
  2. inferred target — record resolution + candidates
  3. ambiguous target — reject without writing
  4. empty-note rejection
  5. successful creation returns a stable id + link
  6. report creation works without telemetry
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog" / "skills" / "bentobug" / "scripts" / "bentobug-report.py"

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
FILENAME_RE = re.compile(r"^([0-9A-HJKMNP-TV-Z]{26})-([a-z0-9-]+)\.json$")


class BentobugReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "store"
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(Path(self.tmp.name) / "home"),
            "BENTO_BENTOBUG_DIR": str(self.store),
        }

    def run_cli(
        self,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env or self.env,
            check=False,
        )

    def assert_no_files_written(self) -> None:
        if self.store.exists():
            self.assertEqual(list(self.store.glob("*.json")), [])

    def load_record(self, payload_path: str) -> dict:
        return json.loads(Path(payload_path).read_text(encoding="utf-8"))

    # ── Acceptance: explicit target ────────────────────────────────────────
    def test_explicit_target_records_verbatim(self) -> None:
        proc = self.run_cli(
            [
                "--note", "launch-work failed to create the linked worktree on macOS",
                "--target", "launch-work",
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        record = self.load_record(out["path"])
        self.assertEqual(record["v"], 1)
        self.assertEqual(record["kind"], "bentobug_report")
        self.assertEqual(record["id"], out["id"])
        self.assertEqual(record["target"], "launch-work")
        self.assertEqual(record["target_resolution"], "explicit")
        self.assertEqual(
            record["note"],
            "launch-work failed to create the linked worktree on macOS",
        )
        self.assertNotIn("candidates", record)

    # ── Acceptance: inferred target ────────────────────────────────────────
    def test_inferred_target_records_resolution(self) -> None:
        proc = self.run_cli(
            [
                "--note", "swarm produced empty triage with one ready issue",
                "--target", "swarm",
                "--target-resolution", "inferred",
                "--candidate", "swarm",
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        record = self.load_record(json.loads(proc.stdout)["path"])
        self.assertEqual(record["target"], "swarm")
        self.assertEqual(record["target_resolution"], "inferred")
        self.assertEqual(record["candidates"], ["swarm"])

    # ── Acceptance: ambiguous target → rejected, nothing written ───────────
    def test_ambiguous_target_is_rejected_without_writing(self) -> None:
        proc = self.run_cli(
            [
                "--note", "a bento skill misbehaved during landing",
                "--candidate", "land-work",
                "--candidate", "swarm",
            ]
        )
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("ambiguous", proc.stderr.lower())
        self.assert_no_files_written()

    def test_missing_target_without_candidates_is_rejected(self) -> None:
        proc = self.run_cli(["--note", "vague bug, no skill named"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("target", proc.stderr.lower())
        self.assert_no_files_written()

    # ── Acceptance: empty / whitespace note rejection ──────────────────────
    def test_empty_note_is_rejected(self) -> None:
        proc = self.run_cli(["--note", "", "--target", "swarm"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("note", proc.stderr.lower())
        self.assert_no_files_written()

    def test_whitespace_only_note_is_rejected(self) -> None:
        proc = self.run_cli(["--note", "   \n\t  ", "--target", "swarm"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("note", proc.stderr.lower())
        self.assert_no_files_written()

    # ── Acceptance: success returns stable id + link ───────────────────────
    def test_success_returns_ulid_id_and_existing_path(self) -> None:
        proc = self.run_cli(["--note", "handoff slot 4 missed cwd", "--target", "handoff"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertRegex(out["id"], ULID_RE)
        path = Path(out["path"])
        self.assertTrue(path.is_file())
        self.assertTrue(str(path).startswith(str(self.store)))

    # ── Filename: ULID + target + note slug ───────────────────────────────
    def test_filename_contains_ulid_target_and_note_slug(self) -> None:
        proc = self.run_cli(
            ["--note", "Swarm produced empty triage with one ready issue",
             "--target", "swarm"]
        )
        path = Path(json.loads(proc.stdout)["path"])
        match = FILENAME_RE.match(path.name)
        self.assertIsNotNone(match, path.name)
        ulid_part, slug_part = match.group(1), match.group(2)
        self.assertEqual(len(ulid_part), 26)
        self.assertTrue(slug_part.startswith("swarm-"))
        self.assertIn("swarm-produced-empty-triage", slug_part)

    def test_filename_omits_note_slug_when_note_has_no_alphanumerics(self) -> None:
        proc = self.run_cli(["--note", "!!!", "--target", "swarm"])
        # !!! is non-empty after .strip(), so the script accepts it; the
        # slug is empty so the filename collapses to <ulid>-<target>.json.
        self.assertEqual(proc.returncode, 0, proc.stderr)
        path = Path(json.loads(proc.stdout)["path"])
        self.assertRegex(path.name, r"^[0-9A-HJKMNP-TV-Z]{26}-swarm\.json$")

    def test_note_slug_is_capped_at_50_chars(self) -> None:
        long_note = "a" * 200
        proc = self.run_cli(["--note", long_note, "--target", "swarm"])
        path = Path(json.loads(proc.stdout)["path"])
        match = FILENAME_RE.match(path.name)
        self.assertIsNotNone(match)
        # slug = "swarm-" + (note slug, ≤50 chars).
        slug_part = match.group(2)
        note_slug = slug_part[len("swarm-"):]
        self.assertLessEqual(len(note_slug), 50)

    def test_note_slug_handles_unicode_and_punctuation(self) -> None:
        proc = self.run_cli(
            ["--note", "Crash!! in hôtel/launch — really??",
             "--target", "launch-work"]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        path = Path(json.loads(proc.stdout)["path"])
        self.assertNotRegex(path.stem, r"--")
        self.assertNotRegex(path.stem, r"-$")
        self.assertRegex(path.stem, r"^[0-9a-zA-Z-]+$")

    # ── One file per report ───────────────────────────────────────────────
    def test_two_reports_create_two_distinct_files(self) -> None:
        p1 = self.run_cli(["--note", "first bug about swarm", "--target", "swarm"])
        p2 = self.run_cli(["--note", "second bug about swarm", "--target", "swarm"])
        out1, out2 = json.loads(p1.stdout), json.loads(p2.stdout)
        self.assertNotEqual(out1["id"], out2["id"])
        self.assertNotEqual(out1["path"], out2["path"])
        self.assertEqual(len(list(self.store.glob("*.json"))), 2)

    # ── created_at ─────────────────────────────────────────────────────────
    def test_record_includes_iso_timestamp_with_timezone(self) -> None:
        proc = self.run_cli(["--note", "x", "--target", "swarm"])
        record = self.load_record(json.loads(proc.stdout)["path"])
        parsed = datetime.fromisoformat(record["created_at"])
        self.assertIsNotNone(parsed.tzinfo)

    # ── Optional context fields ───────────────────────────────────────────
    def test_optional_context_fields_recorded_when_supplied(self) -> None:
        proc = self.run_cli(
            [
                "--note", "land-work failed to push after merge",
                "--target", "land-work",
                "--branch", "feat-x",
                "--worktree", "/wt/feat-x",
                "--cwd", "/projects/example",
                "--context", "ran land-work after merge",
            ]
        )
        record = self.load_record(json.loads(proc.stdout)["path"])
        self.assertEqual(record["branch"], "feat-x")
        self.assertEqual(record["worktree"], "/wt/feat-x")
        self.assertEqual(record["cwd"], "/projects/example")
        self.assertEqual(record["context"], "ran land-work after merge")

    def test_optional_context_fields_absent_when_not_supplied(self) -> None:
        proc = self.run_cli(["--note", "x", "--target", "swarm"])
        record = self.load_record(json.loads(proc.stdout)["path"])
        for key in ("branch", "worktree", "cwd", "context", "candidates"):
            self.assertNotIn(key, record)

    # ── Storage location ─────────────────────────────────────────────────
    def test_xdg_state_home_default_when_no_override(self) -> None:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(Path(self.tmp.name) / "home"),
            "XDG_STATE_HOME": str(Path(self.tmp.name) / "xdg"),
        }
        proc = self.run_cli(["--note", "x", "--target", "swarm"], env=env)
        path = Path(json.loads(proc.stdout)["path"])
        expected = Path(self.tmp.name) / "xdg" / "bento" / "bentobug"
        self.assertTrue(
            str(path).startswith(str(expected)),
            f"{path} not under {expected}",
        )

    def test_bento_bentobug_dir_overrides_xdg(self) -> None:
        env = dict(self.env)
        env["XDG_STATE_HOME"] = str(Path(self.tmp.name) / "xdg-not-used")
        proc = self.run_cli(["--note", "x", "--target", "swarm"], env=env)
        path = Path(json.loads(proc.stdout)["path"])
        self.assertTrue(str(path).startswith(str(self.store)))

    # ── Permissions ───────────────────────────────────────────────────────
    def test_store_file_is_not_world_accessible(self) -> None:
        proc = self.run_cli(["--note", "x", "--target", "swarm"])
        path = Path(json.loads(proc.stdout)["path"])
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode & 0o007, 0, oct(mode))

    # ── Telemetry independence ────────────────────────────────────────────
    def test_works_without_telemetry_data(self) -> None:
        # No CLAUDE_SESSION_ID, no telemetry directory contents.
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(Path(self.tmp.name) / "home"),
            "BENTO_BENTOBUG_DIR": str(self.store),
        }
        proc = self.run_cli(
            ["--note", "compress-docs stripped a non-empty paragraph",
             "--target", "compress-docs"],
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        record = self.load_record(json.loads(proc.stdout)["path"])
        # bentobug records must not collide with telemetry's "script" kind.
        self.assertEqual(record["kind"], "bentobug_report")
        self.assertNotEqual(record["kind"], "script")


if __name__ == "__main__":
    unittest.main()
