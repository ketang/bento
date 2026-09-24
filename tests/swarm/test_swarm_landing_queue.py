import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

from tests.script_test_utils import git, load_module, write

REPO_ROOT = Path(__file__).resolve().parents[2]
QUEUE = REPO_ROOT / "catalog/skills/swarm/scripts/swarm-landing-queue.py"
HOOK_DIRS = [REPO_ROOT / f"catalog/hooks/bento/{rt}/scripts" for rt in ("claude", "codex")]
BRANCH = "feat-ready"


# Long-lived stand-in for the lead's claude process: runs each requested
# command as its child, so helper and hook see the same agent ancestor.
AGENT_LOOP = """
import json, subprocess, sys
for line in sys.stdin:
    req = json.loads(line)
    r = subprocess.run(req["argv"], cwd=sys.argv[1], input=req["stdin"], capture_output=True, text=True)
    print(json.dumps({"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}), flush=True)
"""


class FakeAgent:
    def __init__(self, proc):
        self.proc = proc

    def run(self, argv, stdin=None):
        self.proc.stdin.write(json.dumps({"argv": argv, "stdin": stdin}) + "\n")
        self.proc.stdin.flush()
        return types.SimpleNamespace(**json.loads(self.proc.stdout.readline()))


class LandingQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.repo = base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "T")
        git(self.repo, "config", "user.email", "t@example.com")
        write(self.repo / "a", "a\n")
        git(self.repo, "add", "a")
        git(self.repo, "commit", "-qm", "init")
        git(self.repo, "checkout", "-qb", BRANCH)
        write(self.repo / "b", "b\n")
        git(self.repo, "add", "b")
        git(self.repo, "commit", "-qm", "work")
        git(self.repo, "checkout", "-q", "main")
        # Fake agents: interpreters whose comm is "claude", so /proc ancestry works.
        self.agents = []
        for name in ("lead", "other"):
            d = base / name
            d.mkdir()
            (d / "claude").symlink_to(sys.executable)
            self.agents.append(self.start_agent(d / "claude"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def start_agent(self, agent: Path) -> "FakeAgent":
        env = {**os.environ, "XDG_RUNTIME_DIR": self.tmp.name}
        proc = subprocess.Popen(
            [str(agent), "-c", AGENT_LOOP, str(self.repo)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
        )
        self.addCleanup(lambda: (proc.stdin.close(), proc.wait(), proc.stdout.close()))
        return FakeAgent(proc)

    def under_agent(self, agent, argv, stdin=None):
        return agent.run(argv, stdin)

    def q(self, agent, *args):
        return self.under_agent(agent, [str(QUEUE), *args])

    def stop(self, agent, hook_dir=HOOK_DIRS[0], **payload):
        payload = {"cwd": str(self.repo), "session_id": "s1", **payload}
        return self.under_agent(agent, [str(hook_dir / "check-landing-queue.py")], json.dumps(payload))

    def add(self, agent, branch=BRANCH):
        return self.q(agent, "add", branch, "--worktree", str(self.repo), "--tracker-id", "t-1", "--gate-summary", "ok")

    def entries(self):
        out = subprocess.run([str(QUEUE), "list"], cwd=self.repo, capture_output=True, text=True, check=True)
        return json.loads(out.stdout)["entries"]

    # (a) persistence and helper semantics
    def test_add_and_pop_persist_across_processes(self) -> None:
        self.assertEqual(self.add(self.agents[0]).returncode, 0)
        rows = self.entries()  # separate process = simulated restart
        self.assertEqual([e["branch"] for e in rows], [BRANCH])
        self.assertEqual(rows[0]["tracker_id"], "t-1")
        self.assertIsNotNone(rows[0]["lead_agent"]["pid"])
        self.assertEqual(self.q(self.agents[0], "pop", BRANCH).returncode, 0)
        self.assertEqual(self.entries(), [])

    def test_pop_missing_branch_fails(self) -> None:
        self.assertNotEqual(self.q(self.agents[0], "pop", "nope").returncode, 0)

    def test_concurrent_adds_keep_both(self) -> None:
        procs = [
            subprocess.Popen([str(QUEUE), "add", f"b{i}", "--worktree", "/x"], cwd=self.repo)
            for i in range(8)
        ]
        for p in procs:
            self.assertEqual(p.wait(), 0)
        self.assertEqual(len(self.entries()), 8)

    def test_crash_leftover_temp_file_does_not_corrupt_queue(self) -> None:
        self.add(self.agents[0])
        qdir = Path(git(self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()) / "bento"
        (qdir / ".landing-queue-crashed").write_text("{trunc")
        self.assertEqual([e["branch"] for e in self.entries()], [BRANCH])

    def test_clear_requires_all_and_yes(self) -> None:
        self.add(self.agents[0])
        self.assertNotEqual(self.q(self.agents[0], "clear").returncode, 0)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.q(self.agents[0], "clear", "--all", "--yes").returncode, 0)
        self.assertEqual(self.entries(), [])

    # (b) Stop hook
    def test_hook_blocks_same_agent_for_both_runtimes(self) -> None:
        self.add(self.agents[0])
        for hook_dir in HOOK_DIRS:
            r = self.stop(self.agents[0], hook_dir)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("1 branches are ready to land: " + BRANCH, r.stderr)

    def test_hook_allows_empty_queue_and_different_agent(self) -> None:
        self.assertEqual(self.stop(self.agents[0]).returncode, 0)
        self.add(self.agents[0])
        self.assertEqual(self.stop(self.agents[1]).returncode, 0)

    def test_hook_allows_deferred_only(self) -> None:
        self.add(self.agents[0])
        self.q(self.agents[0], "defer", BRANCH, "--reason", "waiting on review")
        self.assertEqual(self.stop(self.agents[0]).returncode, 0)

    def test_hook_allows_reentry_and_consumes_hold_marker(self) -> None:
        self.add(self.agents[0])
        self.assertEqual(self.stop(self.agents[0], stop_hook_active=True).returncode, 0)
        marker = Path(self.tmp.name) / "bento-check-landing-queue-hold-s1"
        marker.write_text("")
        self.assertEqual(self.stop(self.agents[0]).returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.stop(self.agents[0]).returncode, 2)

    def test_hook_allows_when_branch_already_merged(self) -> None:
        self.add(self.agents[0])
        git(self.repo, "merge", "-q", "--no-edit", BRANCH)
        self.assertEqual(self.stop(self.agents[0]).returncode, 0)

    # (c) doctor report
    def test_doctor_reports_stale_unlanded_entries(self) -> None:
        self.add(self.agents[0])
        for hook_dir in HOOK_DIRS:
            doctor = load_module(hook_dir / "agent-env-doctor.py")
            self.assertEqual(doctor.check_unlanded_queue(self.repo), [])  # fresh entry
            later = time.time() + 2 * 3600
            lines = doctor.check_unlanded_queue(self.repo, now=later)
            self.assertEqual(len(lines), 1)
            self.assertIn("1 ready-but-unlanded branches (oldest: " + BRANCH, lines[0])
        self.q(self.agents[0], "pop", BRANCH)
        self.assertEqual(doctor.check_unlanded_queue(self.repo, now=later), [])


if __name__ == "__main__":
    unittest.main()
