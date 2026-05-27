"""Shared utilities for zolem-based end-to-end tests.

Provides an E2ETestCase base class that manages zolem lifecycle (startup,
port discovery, teardown) and common helpers for git repo initialization
and claude CLI invocation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ZOLEM_STARTUP_TIMEOUT_SECONDS = 10
FIXTURES_BASE = Path(__file__).resolve().parent / "fixtures"


def _have(cmd: str) -> bool:
    """Return True if *cmd* is on PATH."""
    return shutil.which(cmd) is not None


class E2ETestCase(unittest.TestCase):
    """Base class for zolem-backed end-to-end tests.

    Subclasses override class variables to configure the zolem backend:
      PROVIDER   — "anthropic" (default) or "openai"
      BACKEND    — "fixture" (default) or "lorem"
      FIXTURE_NS — subdirectory name under tests/fixtures/ (None omits -local-fixtures-dir)
    """

    PROVIDER: str = "anthropic"
    BACKEND: str = "fixture"
    FIXTURE_NS: str | None = None

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.zolem_log_path = self.root / "zolem.log"
        self.zolem_log = open(self.zolem_log_path, "wb")
        self.calls_file = self.root / "zolem-calls.jsonl"

        cmd = [
            "zolem",
            "-local-addr",
            "127.0.0.1:0",
            "-local-provider",
            self.PROVIDER,
            "-local-backend",
            self.BACKEND,
            "-local-calls-file",
            str(self.calls_file),
        ]
        if self.FIXTURE_NS is not None:
            cmd += ["-local-fixtures-dir", str(FIXTURES_BASE / self.FIXTURE_NS)]

        self.zolem = subprocess.Popen(
            cmd,
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

    # ----- zolem port discovery ------------------------------------------------

    def _wait_for_zolem_port(self, pid: int) -> int:
        """Poll /proc/<pid>/net/tcp until zolem opens its listener."""
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
        """Return the local TCP port that *pid* is listening on, or None."""
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

    # ----- zolem call recording -----------------------------------------------

    def _read_calls(self) -> list[dict]:
        """Return parsed records from the zolem calls file, or [] if absent/empty."""
        if not self.calls_file.exists():
            return []
        lines = self.calls_file.read_text(encoding="utf-8").splitlines()
        result = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return result

    def assertZolemHit(self, min_calls: int = 1) -> None:
        """Assert that zolem intercepted at least *min_calls* API requests."""
        calls = self._read_calls()
        if len(calls) < min_calls:
            zolem_log = ""
            try:
                zolem_log = self.zolem_log_path.read_text(errors="replace")
            except Exception:  # noqa: BLE001
                pass
            self.fail(
                f"Expected at least {min_calls} zolem call(s) but got {len(calls)}. "
                f"calls_file={self.calls_file}  zolem_log:\n{zolem_log}"
            )

    # ----- repo helpers --------------------------------------------------------

    def _git(self, cwd: Path, *args: str) -> None:
        """Run a git command in *cwd*, check=True."""
        subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )

    def _init_repo(self, branch: str = "main") -> Path:
        """Create a fresh git repo with a single commit. Does NOT wire hooks."""
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", branch)
        self._git(repo, "config", "user.name", "E2E Test")
        self._git(repo, "config", "user.email", "e2e-test@example.com")
        (repo / "README.md").write_text("test\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def _run_claude(
        self,
        repo: Path,
        prompt: str = "say ok",
        extra_env: dict | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Invoke ``claude --print`` against the zolem proxy."""
        env = os.environ.copy()
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{self.port}"
        env["ANTHROPIC_API_KEY"] = "sk-zolem-placeholder"
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["claude", "--print", prompt],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
