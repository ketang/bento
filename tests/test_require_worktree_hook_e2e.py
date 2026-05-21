"""End-to-end test for the require-worktree PreToolUse hook.

Drives the real ``claude`` CLI against a mock Anthropic API served by
``zolem`` (https://github.com/ketang/zolem) so we exercise the full path
Claude Code uses to dispatch hooks. This closes the gap that bento-crj
revealed: unit tests pass with a synthetic stdin payload, but cannot catch
bugs in how Claude Code constructs or passes the hook payload at runtime.

The test is skipped when ``zolem`` or ``claude`` is not on PATH, so it is
safe to ship without forcing those binaries into CI.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "bento"
    / "claude"
    / "scripts"
    / "require-worktree.sh"
)
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "e2e-hook"

BLOCKED_MESSAGE = (
    "Blocked: editing files directly on 'main' is not allowed.\n"
    "To disable this check for this repo, add 'require_worktree=false' to "
    ".agent-mode.local.\n"
)

ZOLEM_STARTUP_TIMEOUT_SECONDS = 10


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@unittest.skipUnless(
    _have("zolem") and _have("claude"),
    "zolem and claude must both be on PATH for the e2e hook test",
)
class RequireWorktreeHookE2ETest(unittest.TestCase):
    """Drive Claude Code against a zolem-mocked Anthropic API.

    Each test:
      1. starts zolem on an OS-assigned port serving the e2e-hook fixture
      2. spins up a fresh git repo wired with the require-worktree
         PreToolUse hook in ``.claude/settings.json``
      3. invokes ``claude --print`` with ``ANTHROPIC_BASE_URL`` pointed at
         zolem and a prompt that elicits the fixture's ``Write`` tool call
      4. asserts whether ``probe.txt`` was written and whether the hook's
         block message reached stderr
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.zolem = None
        self.zolem_log_path = self.root / "zolem.log"
        self.zolem_log = open(self.zolem_log_path, "wb")
        # zolem's fixed-listener mode prints the literal "-local-addr" string
        # in its startup log, not the resolved port, so we discover the bound
        # port by inspecting the process's listening socket from /proc.
        # TODO: see zolem README; if a future zolem release prints the
        # resolved port in its startup banner, parse that instead of using
        # /proc for port discovery.
        self.zolem = subprocess.Popen(
            [
                "zolem",
                "-local-addr",
                "127.0.0.1:0",
                "-local-provider",
                "anthropic",
                "-local-backend",
                "fixture",
                "-local-fixtures-dir",
                str(FIXTURES_DIR.parent),
            ],
            stdout=self.zolem_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.port = self._wait_for_zolem_port(self.zolem.pid)

    def tearDown(self) -> None:
        proc = self.zolem
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        try:
            self.zolem_log.close()
        except Exception:
            pass
        self.tmp.cleanup()

    # ----- helpers ----------------------------------------------------------

    def _wait_for_zolem_port(self, pid: int) -> int:
        """Poll ``/proc/<pid>/net/tcp`` until zolem opens its listener."""
        deadline = time.monotonic() + ZOLEM_STARTUP_TIMEOUT_SECONDS
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if self.zolem.poll() is not None:
                self.fail(
                    f"zolem exited early (rc={self.zolem.returncode}); "
                    f"log:\n{self.zolem_log_path.read_text(errors='replace')}"
                )
            try:
                port = self._read_listen_port(pid)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                port = None
            if port:
                return port
            time.sleep(0.1)
        msg = f"zolem did not open a listening port within {ZOLEM_STARTUP_TIMEOUT_SECONDS}s"
        if last_err is not None:
            msg += f" (last error: {last_err!r})"
        self.fail(msg)

    @staticmethod
    def _read_listen_port(pid: int) -> int | None:
        """Return the local TCP port that ``pid`` is listening on, or None."""
        fd_dir = Path(f"/proc/{pid}/fd")
        socket_inodes: set[str] = set()
        try:
            entries = list(fd_dir.iterdir())
        except FileNotFoundError:
            return None
        for entry in entries:
            try:
                target = os.readlink(entry)
            except OSError:
                continue
            m = re.match(r"socket:\[(\d+)\]", target)
            if m:
                socket_inodes.add(m.group(1))
        if not socket_inodes:
            return None
        tcp_path = Path(f"/proc/{pid}/net/tcp")
        try:
            tcp_text = tcp_path.read_text()
        except OSError:
            return None
        # state 0A = LISTEN
        for line in tcp_text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 10:
                continue
            local, state, inode = parts[1], parts[3], parts[9]
            if state != "0A" or inode not in socket_inodes:
                continue
            _, hex_port = local.split(":")
            return int(hex_port, 16)
        return None

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )

    def _init_repo(self, branch: str = "main") -> Path:
        repo = self.root / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", branch)
        self._git(repo, "config", "user.name", "Require Worktree E2E")
        self._git(repo, "config", "user.email", "require-worktree-e2e@example.com")
        (repo / "README.md").write_text("test\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")

        # Wire the hook into project-level Claude settings so the test does
        # not have to touch the developer's ~/.claude/settings.json.
        settings_dir = repo / ".claude"
        settings_dir.mkdir()
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Write",
                        "hooks": [
                            {"type": "command", "command": str(HOOK_SCRIPT)}
                        ],
                    }
                ]
            }
        }
        (settings_dir / "settings.json").write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )
        return repo

    def _run_claude(self, repo: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{self.port}"
        # Force a sentinel API key so the SDK does not try to use a real one.
        env["ANTHROPIC_API_KEY"] = "sk-zolem-placeholder"
        return subprocess.run(
            [
                "claude",
                "--print",
                "Please call the Write tool to create probe.txt.",
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    # ----- tests ------------------------------------------------------------

    def test_blocked_on_main(self) -> None:
        repo = self._init_repo(branch="main")

        result = self._run_claude(repo)

        self.assertFalse(
            (repo / "probe.txt").exists(),
            msg=f"probe.txt should not have been written on main; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        combined = result.stderr + result.stdout
        self.assertIn(
            "Blocked: editing files directly on 'main' is not allowed.",
            combined,
            msg=f"expected block message in claude output; got: {combined!r}",
        )

    def test_allowed_on_feature_branch(self) -> None:
        repo = self._init_repo(branch="main")
        self._git(repo, "checkout", "-q", "-b", "feature-e2e")

        result = self._run_claude(repo)

        self.assertTrue(
            (repo / "probe.txt").exists(),
            msg=f"probe.txt should have been written on a feature branch; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )

    def test_allowed_with_opt_out(self) -> None:
        repo = self._init_repo(branch="main")
        (repo / ".agent-mode.local").write_text(
            "require_worktree=false\n", encoding="utf-8"
        )

        result = self._run_claude(repo)

        self.assertTrue(
            (repo / "probe.txt").exists(),
            msg=f"probe.txt should have been written with opt-out; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )


if __name__ == "__main__":
    unittest.main()
