"""systemd transient-scope provider: blocked executor -> scope + verified limits -> exec."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")
SLICE = "system.slice"
NICE_PREFIX = ["nice", "-n", "10", "ionice", "-c", "3"]


class ScopeError(Exception):
    pass


def unit_name(lease_id: str) -> str:
    return f"bento-governor-{lease_id}.scope"


def start_transient_unit_args(unit: str, pid: int, memory_max: int) -> list[str]:
    """busctl arguments for Manager.StartTransientUnit(name, mode, properties, aux)."""
    return [
        "busctl", "--system", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
        "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
        unit, "fail", "6",
        "PIDs", "au", "1", str(pid),
        "MemoryMax", "t", str(memory_max),
        "MemorySwapMax", "t", "0",
        "OOMPolicy", "s", "kill",
        "Slice", "s", SLICE,
        "Description", "s", "bento-governor job",
        "0",
    ]


def _read_int(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
        return int(text)
    except (OSError, ValueError):
        return None


def _events(path: Path) -> dict[str, int] | None:
    try:
        return {k: int(v) for k, v in (line.split() for line in path.read_text().splitlines())}
    except (OSError, ValueError):
        return None


class ScopeHandle:
    """A running scope. Keeps the last-seen OOM count so a vanished cgroup cannot erase evidence."""

    def __init__(self, unit: str | None, cgroup_path: str | None, executor_pid: int | None,
                 child_pid: int | None = None):
        self.unit, self.cgroup_path, self.executor_pid, self.child_pid = unit, cgroup_path, executor_pid, child_pid
        self._status: int | None = None
        self._oom = 0
        self._oom_known = True
        self._peak: int | None = None

    @property
    def path(self) -> Path | None:
        return Path(self.cgroup_path) if self.cgroup_path else None

    def _reap_child(self) -> None:
        if self.child_pid is None or self._status is not None:
            return
        try:
            pid, raw = os.waitpid(self.child_pid, os.WNOHANG)
        except ChildProcessError:
            self._status = 70
            return
        if pid:
            self._status = os.waitstatus_to_exitcode(raw)

    def _sample(self) -> None:
        path = self.path
        if path is None:
            return
        events = _events(path / "memory.events")
        if events is not None:
            self._oom = max(self._oom, events.get("oom_kill", 0))
        peak = _read_int(path / "memory.peak")
        if peak is not None:
            self._peak = peak

    def is_empty(self) -> bool:
        self._reap_child()
        if self.path is None:  # uncontained bypass: only the child process itself
            return self._status is not None
        self._sample()
        events = _events(self.path / "cgroup.events")
        if events is None:
            # cgroup removed: systemd tore the empty scope down. Only trust it after we saw the child exit.
            return not self.path.exists() and self._status is not None
        return events.get("populated") == 0 and self._status is not None

    def oom_kills(self) -> int | None:
        self._sample()
        return self._oom if self._oom_known else None

    def peak_memory(self) -> int | None:
        self._sample()
        return self._peak

    def exit_status(self) -> int | None:
        self._reap_child()
        return self._status

    def kill(self) -> None:
        path = self.path
        if path is not None:
            try:
                (path / "cgroup.kill").write_text("1")
                return
            except OSError:
                pass
        if self.child_pid is not None:
            try:
                os.kill(self.child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def contains_pid(self, pid: int) -> bool:
        path = self.path
        if path is None:
            return False
        try:
            return str(pid) in (path / "cgroup.procs").read_text().split()
        except OSError:
            return False


class SystemdScopes:
    def __init__(self, unit_bytes: int, cgroup_root: Path = CGROUP_ROOT):
        self.unit_bytes, self.cgroup_root = unit_bytes, cgroup_root

    def _cgroup(self, unit: str) -> Path:
        return self.cgroup_root / SLICE / unit

    def _spawn_blocked(self, request) -> tuple[int, int]:
        """Fork an executor under the caller UID that blocks on a pipe before exec."""
        read_end, write_end = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(write_end)
                os.setgroups([])
                os.setgid(request.gid)
                os.setuid(request.uid)
                os.chdir(request.cwd)
                if os.read(read_end, 1) != b"1":
                    os._exit(70)
                os.close(read_end)
                os.execvpe(NICE_PREFIX[0], NICE_PREFIX + list(request.argv), request.env)
            except BaseException:
                os._exit(126)
        os.close(read_end)
        return pid, write_end

    def launch(self, lease, request):
        pid, gate = self._spawn_blocked(request)
        unit = unit_name(lease.lease_id)
        path = self._cgroup(unit)
        memory_max = lease.effective_weight * self.unit_bytes
        try:
            subprocess.run(start_transient_unit_args(unit, pid, memory_max), check=True,
                           capture_output=True, timeout=30)
            self._verify(path, pid, memory_max)
        except Exception as exc:
            os.close(gate)
            self._kill_executor(pid)
            raise ScopeError(f"scope setup failed: {exc}") from exc
        handle = ScopeHandle(unit, str(path), pid, child_pid=pid)
        handle.gate = gate
        return handle

    def release_executor(self, handle: ScopeHandle) -> None:
        """Step 5: let the executor exec, only after the lease row is durable."""
        gate = getattr(handle, "gate", None)
        if gate is not None:
            os.write(gate, b"1")
            os.close(gate)
            handle.gate = None

    def launch_uncontained(self, lease, request):
        pid, gate = self._spawn_blocked(request)
        handle = ScopeHandle(None, None, pid, child_pid=pid)
        handle.gate = gate
        return handle

    def _verify(self, path: Path, pid: int, memory_max: int) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not path.exists():
            time.sleep(0.05)
        if str(pid) not in (path / "cgroup.procs").read_text().split():
            raise ScopeError("executor not in scope cgroup")
        if _read_int(path / "memory.max") != memory_max:
            raise ScopeError("memory.max not applied")
        if _read_int(path / "memory.swap.max") != 0:
            raise ScopeError("memory.swap.max not applied")

    def _kill_executor(self, pid: int) -> None:
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass

    def abort(self, lease):
        """Kill any scope for this lease; return a handle whose is_empty() is proven, else None."""
        unit = unit_name(lease.lease_id)
        subprocess.run(["systemctl", "kill", "--kill-whom=all", "--signal=SIGKILL", unit],
                       capture_output=True, timeout=30)
        handle = ScopeHandle(unit, str(self._cgroup(unit)), lease.executor_pid)
        handle._status = 0  # abort path: no child status to wait for
        return handle

    def adopt(self, lease):
        if not lease.scope_cgroup:
            return None
        path = Path(lease.scope_cgroup)
        if path.exists() and _events(path / "cgroup.events") is None:
            return None  # exists but unreadable: unverifiable
        handle = ScopeHandle(lease.scope_unit, lease.scope_cgroup, lease.executor_pid)
        handle._status = None if path.exists() else 0
        if path.exists():
            handle._status = 0  # original child is not ours after a restart; status unrecoverable
            handle._oom_known = _events(path / "memory.events") is not None
        return handle

    def executor_gone(self, lease) -> bool:
        if lease.executor_pid is None:
            return True
        try:
            os.kill(lease.executor_pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def unit_absent(self, lease) -> bool:
        result = subprocess.run(["systemctl", "show", "-p", "LoadState", "--value",
                                 unit_name(lease.lease_id)], capture_output=True, text=True, timeout=30)
        return result.returncode == 0 and result.stdout.strip() == "not-found"
