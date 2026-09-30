"""Host service: Unix-socket transport around the admission engine (runs as a system service)."""

from __future__ import annotations

import array
import json
import os
import select
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

from . import CONTRACT_VERSION
from .config import ConfigError, load
from .engine import Engine, Request
from .pressure import sample_signals
from .scopes import SystemdScopes
from .store import Store, StoreError

SOCKET_PATH = "/run/bento-governor/v1.sock"
TOKEN_ENV = "BENTO_GOVERNOR_LEASE_TOKEN"
MAX_REQUEST_BYTES = 8 * 1024 * 1024


def _peer(connection: socket.socket) -> tuple[int, int, int]:
    pid, uid, gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                            struct.calcsize("3i")))
    return pid, uid, gid


def _receive(connection: socket.socket) -> tuple[dict, list[int]]:
    """Read one JSON line plus any SCM_RIGHTS descriptors sent with it."""
    buffer, fds = bytearray(), array.array("i")
    while b"\n" not in buffer:
        data, ancillary, _flags, _addr = connection.recvmsg(65536, socket.CMSG_LEN(3 * fds.itemsize))
        if not data:
            raise OSError("client closed before sending a request")
        buffer.extend(data)
        for level, kind, payload in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                fds.frombytes(payload[: len(payload) - len(payload) % fds.itemsize])
        if len(buffer) > MAX_REQUEST_BYTES:
            raise OSError("request too large")
    message = json.loads(buffer.split(b"\n", 1)[0])
    if not isinstance(message, dict) or message.get("schema_version") != CONTRACT_VERSION:
        raise ValueError("incompatible protocol major")
    return message, list(fds)


class Service:
    def __init__(self, config: dict, store: Store, engine: Engine):
        self.config, self.store, self.engine = config, store, engine
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)

    def caller_allowed(self, uid: int, gid: int) -> bool:
        return uid in self.config["allowed_uids"] or gid in self.config["allowed_gids"]

    def pressure(self, weight: int, exclusive: bool, cwd: str, env: dict) -> dict:
        w = self.config["capacity"] if exclusive else weight
        return sample_signals(self.config, cwd, w, self.config["capacity"], env)

    def authorize_bypass(self, request: Request) -> bool:
        """Operator allowlist + real TTY + interactive polkit challenge for the peer process."""
        if request.operator_uid not in self.config["operator_uids"] or not request.operator_tty:
            return False
        result = subprocess.run(
            ["pkcheck", "--action-id", "org.bento.governor.bypass", "--process", str(request.peer_pid),
             "--allow-user-interaction"], capture_output=True, timeout=120)
        return result.returncode == 0

    @staticmethod
    def _peer_tty(pid: int) -> str | None:
        """The peer's real controlling terminal, read from /proc (never client-supplied)."""
        try:
            target = os.readlink(f"/proc/{pid}/fd/0")
        except OSError:
            return None
        return target if target.startswith(("/dev/pts/", "/dev/tty")) else None

    def _request(self, message: dict, peer: tuple[int, int, int]) -> Request:
        pid, uid, gid = peer
        env = {str(k): str(v) for k, v in dict(message.get("environment", {})).items()}
        token = env.pop(TOKEN_ENV, None)
        bypass = message.get("bypass")
        return Request(
            uid=uid, gid=gid, repo=str(message["repo"]), label=str(message["label"]),
            argv=[str(a) for a in message["command"]], cwd=str(message["cwd"]), env=env,
            weight=int(message.get("weight", 1)), exclusive=bool(message.get("exclusive")),
            max_wait=message.get("max_wait"), bypass=bypass, reason=message.get("reason"),
            operator_uid=uid if bypass else None,
            operator_tty=self._peer_tty(pid) if bypass else None,
            fds=list(message.get("_fds", [])), peer_pid=pid, parent_token=token)

    def handle_run(self, connection: socket.socket, message: dict, peer) -> dict:
        request = self._request(message, peer)
        with self.lock:
            ticket = self.engine.submit(request)
        nested_pid = None
        if ticket.state == "running" and ticket.token is None:  # re-entrant: run inside the outer scope
            try:
                nested_pid = self.engine.scopes.run_nested(ticket.handle, request)
            except Exception as exc:
                return {"exit_code": 70, "result": {"schema_version": 1, "outcome": "infra-error",
                        "lease_id": ticket.lease.lease_id, "wait_seconds": 0,
                        "child_exit_code": None, "detail": str(exc)}}
        while True:
            if nested_pid is not None:
                done, raw = os.waitpid(nested_pid, os.WNOHANG)
                if done:
                    code = os.waitstatus_to_exitcode(raw)
                    return {"exit_code": code if code >= 0 else 128 - code, "result": {
                        "schema_version": 1, "outcome": "completed" if code == 0 else "child-failed",
                        "lease_id": ticket.lease.lease_id, "wait_seconds": 0, "child_exit_code": code}}
            else:
                with self.lock:
                    self.engine.poll()
                    if ticket.state == "done":
                        return ticket.result
            readable, _, _ = select.select([connection], [], [], 0.5)
            if readable:
                data = connection.recv(64, socket.MSG_PEEK)
                if not data:  # client vanished (SIGKILL): cancel queue entry / mark client-lost
                    with self.lock:
                        self.engine.cancel(ticket)
                    return {"exit_code": 70}
                line = connection.recv(64).strip()
                if line in (b"TERM", b"INT"):
                    if nested_pid is not None:
                        os.kill(nested_pid, 15)
                    else:
                        with self.lock:
                            self.engine.terminate(ticket)

    def serve_connection(self, connection: socket.socket) -> None:
        fds: list[int] = []
        try:
            peer = _peer(connection)
            if not self.caller_allowed(peer[1], peer[2]):
                connection.sendall(b'{"schema_version":1,"exit_code":69,"result":{"schema_version":1,"outcome":"denied","lease_id":null,"wait_seconds":0,"child_exit_code":null}}\n')
                return
            message, fds = _receive(connection)
            action = message.get("action")
            if action == "run":
                if fds:
                    message["_fds"] = fds
                response = self.handle_run(connection, message, peer)
            elif action == "signals":
                weight = self.config["capacity"] if message.get("exclusive") else int(message.get("weight", 1))
                response = {"exit_code": 0, "signals": self.pressure(
                    weight, False, str(message["cwd"]), dict(message.get("environment", {})))}
            elif action == "events":
                with self.lock:
                    response = {"exit_code": 0, "events": self.store.events(message.get("since"))}
            else:
                raise ValueError("unknown action")
            connection.sendall(json.dumps({"schema_version": CONTRACT_VERSION, **response},
                                          separators=(",", ":")).encode() + b"\n")
        except (OSError, ValueError, KeyError, StoreError):
            pass  # connection-scoped failure; the client reports infra-error (70)
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            connection.close()

    def poller(self) -> None:
        while True:
            time.sleep(self.config["poll_seconds"])
            with self.lock:
                self.engine.poll()


def serve(config_path: Path) -> int:
    try:
        config = load(config_path)
        state = Path(config["state_dir"])
        state.mkdir(parents=True, exist_ok=True)
        store = Store(state / "state.sqlite3")
    except (ConfigError, StoreError, OSError) as exc:
        print(f"bento-governor-v1: {exc}")
        return 70
    scopes = SystemdScopes(config["unit_bytes"])
    holder: dict[str, Service] = {}
    engine = Engine(store, config, lambda *a: holder["s"].pressure(*a), scopes, time.monotonic,
                    lambda r: holder["s"].authorize_bypass(r))
    service = holder["s"] = Service(config, store, engine)
    unresolved = engine.reconcile()
    if unresolved:
        print(f"bento-governor-v1: admission closed; unverifiable leases: {unresolved}")
    socket_path = Path(SOCKET_PATH)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    os.chmod(socket_path, 0o666)  # authorization is by SO_PEERCRED against the config allowlist
    listener.listen(64)
    threading.Thread(target=service.poller, daemon=True).start()
    while True:
        connection, _ = listener.accept()
        threading.Thread(target=service.serve_connection, args=(connection,), daemon=True).start()
