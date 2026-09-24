"""Tests for bd-review-followup-guard.py (bento-c96u.9).

A fake `bd` on PATH serves a JSON state file, so the hook's decisions are
tested without a real Beads DB.
"""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "catalog" / "hooks" / "bento" / "claude" / "scripts" / "bd-review-followup-guard.py"
LAND_WORK_SKILL = REPO_ROOT / "catalog" / "skills" / "land-work" / "SKILL.md"

FAKE_BD = """#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_BD_STATE"]))
args = sys.argv[1:]
if args[0] == "show":
    issue = state["issues"].get(args[1])
    print(json.dumps([issue] if issue else []))
    sys.exit(0 if issue else 1)
if args[:2] == ["dep", "list"]:
    print(json.dumps([{"id": i} for i in state["discovered_from"].get(args[2], [])]))
elif args[0] == "list":
    print(json.dumps([{"id": i} for i, d in state["issues"].items() if "review-followup" in d["labels"]]))
"""


class BdReviewFollowupGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        bindir = self.root / "bin"
        bindir.mkdir()
        fake = bindir / "bd"
        fake.write_text(FAKE_BD, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_BD_STATE": str(self.root / "state.json"),
        }
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        self.repo = repo
        self.state({"P": [], "Q": ["review-followup"]}, {})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def state(self, labels: dict, discovered_from: dict) -> None:
        issues = {i: {"id": i, "labels": ls} for i, ls in labels.items()}
        for children in discovered_from.values():
            for child in children:
                issues.setdefault(child, {"id": child, "labels": ["review-followup"]})
        (self.root / "state.json").write_text(
            json.dumps({"issues": issues, "discovered_from": discovered_from}), encoding="utf-8",
        )

    def run_hook(self, command: str) -> subprocess.CompletedProcess[str]:
        payload = json.dumps({"tool_name": "Bash", "cwd": str(self.repo), "tool_input": {"command": command}})
        return subprocess.run(
            [str(HOOK)], input=payload, env=self.env, cwd=self.root,
            capture_output=True, text=True, check=False,
        )

    def test_first_followup_is_allowed(self) -> None:
        result = self.run_hook("bd create 'Minors' -l review-followup --deps discovered-from:P")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_second_followup_same_parent_is_blocked(self) -> None:
        self.state({"P": []}, {"P": ["F1"]})
        result = self.run_hook("bd create 'More' --labels review-followup --deps discovered-from:P")
        self.assertEqual(result.returncode, 2)
        self.assertIn("at most one follow-up", result.stderr)

    def test_followup_of_followup_is_blocked(self) -> None:
        result = self.run_hook("rtk bd create 'X' --labels=review-followup --parent Q")
        self.assertEqual(result.returncode, 2)
        self.assertIn("follow-ups of follow-ups", result.stderr)

    def test_waiver_names_parent(self) -> None:
        (self.repo / ".agent-mode.local").write_text("review_followup_waiver=Q\n", encoding="utf-8")
        result = self.run_hook("bd create 'X' -l review-followup --parent Q")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unlabelled_create_is_unaffected(self) -> None:
        self.state({"P": [], "Q": ["review-followup"]}, {"P": ["F1"]})
        for cmd in (
            "bd create 'X' --parent Q",
            "bd create 'X' -l other --deps discovered-from:P",
        ):
            self.assertEqual(self.run_hook(cmd).returncode, 0, cmd)

    def test_other_bd_commands_unaffected(self) -> None:
        self.assertEqual(self.run_hook("bd show Q").returncode, 0)

    def test_fails_open_without_bd(self) -> None:
        self.env["PATH"] = "/usr/bin:/bin"
        result = self.run_hook("bd create 'X' -l review-followup --parent Q")
        self.assertEqual(result.returncode, 0)


class LandWorkFollowupPolicyDocTest(unittest.TestCase):
    def test_step4_states_the_cap(self) -> None:
        text = LAND_WORK_SKILL.read_text(encoding="utf-8")
        self.assertIn("at most one follow-up", text)
        self.assertIn("review-followup", text)


if __name__ == "__main__":
    unittest.main()
