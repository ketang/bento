"""Tests for bd-review-followup-guard.py (bento-c96u.9).

A fake `bd` on PATH serves a JSON state file, so the hook's decisions are
tested without a real Beads DB.
"""

import json
import os
import stat
import shutil
import subprocess
import sys
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
with open(os.environ["FAKE_BD_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
fail = state.get("fail", [])
if args[:1] == ["show"] and len(args) == 3 and args[2] == "--json":
    if "show" in fail:
        sys.exit(1)
    issue = state["issues"].get(args[1])
    print(json.dumps([issue] if issue else []))
elif args[:2] == ["dep", "list"] and args[3:] == ["--direction=up", "--json"]:
    if "dep" in fail:
        sys.exit(1)
    print(json.dumps(state["dependents"].get(args[2], [])))
elif args == ["list", "--label", "review-followup", "--all", "-n", "0", "--json"]:
    print(json.dumps([{"id": i} for i, d in state["issues"].items() if "review-followup" in d["labels"]]))
else:
    with open(os.environ["FAKE_BD_LOG"], "a") as log:
        log.write("UNEXPECTED\\n")
    sys.exit(99)
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
        self.log = self.root / "calls.log"
        self.env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_BD_STATE": str(self.root / "state.json"),
            "FAKE_BD_LOG": str(self.log),
        }
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        self.repo = repo
        self.state()

    def tearDown(self) -> None:
        self.assertNotIn("UNEXPECTED", self.calls(), "hook invoked bd with unexpected argv")
        self.tmp.cleanup()

    def calls(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def state(self, existing: list[str] | None = None, fail: list[str] | None = None) -> None:
        """P is a plain issue; Q is a review-followup; `existing` are review-followup
        issues discovered from P (dependency records as `bd dep list` prints them)."""
        issues = {"P": {"id": "P", "labels": []}, "Q": {"id": "Q", "labels": ["review-followup"]}}
        for child in existing or []:
            issues[child] = {"id": child, "labels": ["review-followup"]}
        dependents = {"P": [{"id": c, "dependency_type": "discovered-from"} for c in existing or []]}
        (self.root / "state.json").write_text(
            json.dumps({"issues": issues, "dependents": dependents, "fail": fail or []}),
            encoding="utf-8",
        )

    def run_hook(self, command: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
        payload = json.dumps({"tool_name": "Bash", "cwd": str(self.repo), "tool_input": {"command": command}})
        return subprocess.run(
            [sys.executable, str(HOOK)], input=payload, env=env or self.env, cwd=self.root,
            capture_output=True, text=True, check=False,
        )

    def assertAllowed(self, command: str) -> None:
        result = self.run_hook(command)
        self.assertEqual(result.returncode, 0, f"{command}\n{result.stderr}")

    def assertBlocked(self, command: str, phrase: str) -> None:
        result = self.run_hook(command)
        self.assertEqual(result.returncode, 2, f"{command}\n{result.stderr}")
        self.assertIn(phrase, result.stderr)

    # -- the cap ---------------------------------------------------------

    def test_first_followup_is_allowed(self) -> None:
        self.assertAllowed("bd create 'Minors' -l review-followup --deps discovered-from:P")
        self.assertIn('"dep", "list", "P"', self.calls())  # it really checked

    def test_second_followup_same_parent_is_blocked(self) -> None:
        self.state(existing=["F1"])
        self.assertBlocked(
            "bd create 'More' --labels review-followup --deps discovered-from:P", "at most one follow-up",
        )

    def test_existing_child_via_parent_child_counts(self) -> None:
        self.state(existing=["F1"])
        deps = json.loads((self.root / "state.json").read_text())
        deps["dependents"]["P"] = [{"id": "F1", "dependency_type": "parent-child"}]
        (self.root / "state.json").write_text(json.dumps(deps))
        self.assertBlocked("bd create 'More' -l review-followup --parent P", "at most one follow-up")

    def test_unrelated_dependents_do_not_count(self) -> None:
        self.state(existing=["F1"])
        deps = json.loads((self.root / "state.json").read_text())
        deps["dependents"]["P"] = [{"id": "F1", "dependency_type": "blocks"}]
        (self.root / "state.json").write_text(json.dumps(deps))
        self.assertAllowed("bd create 'More' -l review-followup --deps discovered-from:P")

    def test_followup_of_followup_is_blocked(self) -> None:
        self.assertBlocked("rtk bd create 'X' --labels=review-followup --parent Q", "follow-ups of follow-ups")

    def test_flag_spellings(self) -> None:
        self.assertBlocked("bd create X -lreview-followup --parent=Q", "follow-ups of follow-ups")
        self.assertBlocked(
            "bd create X -l a,review-followup --deps blocks:P,discovered-from:Q", "follow-ups of follow-ups",
        )
        self.assertBlocked("bd create X --deps a,discovered-from:Q -l review-followup", "follow-ups of follow-ups")

    def test_parent_child_inherits_label_and_is_blocked(self) -> None:
        self.assertBlocked("bd create 'X' --parent Q", "follow-ups of follow-ups")

    def test_no_inherit_labels_and_plain_parent_are_allowed(self) -> None:
        self.assertAllowed("bd create 'X' --parent Q --no-inherit-labels")
        self.assertAllowed("bd create 'X' --parent P")

    # -- command parsing --------------------------------------------------

    def test_quoted_operators_do_not_hide_the_create(self) -> None:
        self.assertBlocked(
            "cd /x && bd create 'a; b' -l review-followup --parent Q", "follow-ups of follow-ups",
        )
        self.assertBlocked(
            "bd create a --body 'x && y | z' -l review-followup --parent Q", "follow-ups of follow-ups",
        )

    def test_heredoc_body_is_ignored_and_following_create_seen(self) -> None:
        command = "cat > n.md <<'EOF'\nit's an unbalanced quote; bd create X -l review-followup --parent P\nEOF\n"
        self.assertAllowed(command)
        self.assertEqual(self.calls(), "")
        self.assertBlocked(command + "bd create Y -l review-followup --parent Q", "follow-ups of follow-ups")

    def test_bash_dash_c_is_unwrapped(self) -> None:
        self.assertBlocked("bash -c \"bd create X -l review-followup --parent Q\"", "follow-ups of follow-ups")

    def test_multiple_creates_in_one_command(self) -> None:
        self.assertBlocked(
            "bd create A -l review-followup --parent P; bd create B -l review-followup --parent Q",
            "follow-ups of follow-ups",
        )

    # -- opt-outs ---------------------------------------------------------

    def test_waiver_names_parent(self) -> None:
        (self.repo / ".agent-mode.local").write_text("review_followup_waiver=Q\n", encoding="utf-8")
        self.assertAllowed("bd create 'X' -l review-followup --parent Q")

    def test_waiver_comma_list(self) -> None:
        (self.repo / ".agent-mode.local").write_text("review_followup_waiver=Z, Q\n", encoding="utf-8")
        self.assertAllowed("bd create 'X' -l review-followup --parent Q")
        self.state(existing=["F1"])
        self.assertBlocked("bd create 'X' -l review-followup --parent P", "at most one follow-up")

    def test_guard_can_be_disabled(self) -> None:
        (self.repo / ".agent-mode.local").write_text("review_followup_guard=false\n", encoding="utf-8")
        self.assertAllowed("bd create 'X' -l review-followup --parent Q")

    # -- unaffected commands ---------------------------------------------

    def test_unlabelled_create_is_unaffected(self) -> None:
        self.state(existing=["F1"])
        self.assertAllowed("bd create 'X' -l other --deps discovered-from:P")
        self.assertAllowed("bd create 'X' --deps discovered-from:P")
        self.assertEqual(self.calls(), "")

    def test_other_bd_commands_unaffected(self) -> None:
        self.assertAllowed("bd show Q")
        self.assertAllowed("bd update Q --labels review-followup")

    def test_followup_without_parent_is_unaffected(self) -> None:
        self.assertAllowed("bd create 'X' -l review-followup")

    # -- fail-open behavior (intentional: never block on tooling errors) ------

    def test_bd_show_failure_fails_open(self) -> None:
        self.state(fail=["show"])
        self.assertAllowed("bd create X -l review-followup --parent Q")

    def test_bd_dep_list_failure_fails_open(self) -> None:
        self.state(existing=["F1"], fail=["dep"])
        self.assertAllowed("bd create X -l review-followup --deps discovered-from:P")
        self.assertIn('"dep", "list"', self.calls())

    def test_fails_open_when_bd_absent(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        self.assertIsNone(shutil.which("bd", path=str(empty)))
        result = self.run_hook(
            "bd create X -l review-followup --parent Q", env={**self.env, "PATH": str(empty)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unbalanced_quote_fails_open_and_logs(self) -> None:
        result = self.run_hook("bd create 'X -l review-followup --parent Q")
        self.assertEqual(result.returncode, 0)
        self.assertIn("failing open", result.stderr)


class LandWorkFollowupPolicyDocTest(unittest.TestCase):
    def test_step4_states_the_cap(self) -> None:
        text = LAND_WORK_SKILL.read_text(encoding="utf-8")
        self.assertIn("at most one follow-up", text)
        self.assertIn("without operator approval", text)


if __name__ == "__main__":
    unittest.main()
