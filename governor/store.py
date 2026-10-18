"""SQLite lease registry and durable audit stream for governor protocol v1.

``Store(path)`` opens a WAL/FULL database. ``reserve(...)`` atomically checks
weighted capacity, inserts a live lease, and commits its acquire/bypass event;
it returns ``None`` after an audited capacity denial. ``get_lease`` and
``active_leases`` support restart reconciliation. ``attach_executor`` and
``attach_scope`` persist launch identity before the executor is unblocked.
``release`` requires the caller's verified-empty assertion and commits the
release event with the state change. ``recover_unattached`` requires evidence
that both the blocked executor is gone and the deterministic unit is absent.
``record_event``, ``events``, and ``events_jsonl`` expose the audit stream.

The service owns OS-level evidence: this module never infers cgroup emptiness
from a child exit or frees a lease on an SQLite/audit failure. Store errors are
raised as ``StoreError``; callers must fail closed.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class StoreError(RuntimeError):
    """Durable state could not be trusted or changed."""


@dataclass(frozen=True)
class Lease:
    lease_id: str
    uid: int
    repo: str
    label: str
    requested_weight: int
    effective_weight: int
    exclusive: bool
    bypass: bool
    executor_pid: int | None
    scope_unit: str | None
    scope_cgroup: str | None
    released_at: str | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS leases (
    lease_id TEXT PRIMARY KEY,
    uid INTEGER NOT NULL,
    repo TEXT NOT NULL,
    label TEXT NOT NULL,
    requested_weight INTEGER NOT NULL CHECK (requested_weight > 0),
    effective_weight INTEGER NOT NULL CHECK (effective_weight > 0),
    exclusive INTEGER NOT NULL,
    bypass INTEGER NOT NULL,
    executor_pid INTEGER,
    scope_unit TEXT,
    scope_cgroup TEXT,
    acquired_at TEXT NOT NULL,
    released_at TEXT
);
CREATE INDEX IF NOT EXISTS active_leases ON leases(released_at);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.path, timeout=30, isolation_level=None,
                                       check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            mode = self._db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            self._db.execute("PRAGMA synchronous=FULL")
            if mode.lower() != "wal" or self._db.execute("PRAGMA synchronous").fetchone()[0] != 2:
                raise StoreError("WAL/FULL durability unavailable")
            self._db.executescript(_SCHEMA)
        except (OSError, sqlite3.Error) as exc:
            raise StoreError(f"cannot open governor state: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._db is None:
                raise StoreError("governor state is closed")
            try:
                self._db.execute("BEGIN IMMEDIATE")
                yield self._db
                self._db.execute("COMMIT")
            except sqlite3.Error as exc:
                self._db.execute("ROLLBACK")
                raise StoreError(f"governor state transaction failed: {exc}") from exc
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    @staticmethod
    def _lease(row: sqlite3.Row) -> Lease:
        return Lease(row["lease_id"], row["uid"], row["repo"], row["label"],
                     row["requested_weight"], row["effective_weight"],
                     bool(row["exclusive"]), bool(row["bypass"]),
                     row["executor_pid"], row["scope_unit"], row["scope_cgroup"],
                     row["released_at"])

    @staticmethod
    def _event(db: sqlite3.Connection, event_type: str, *, lease: Lease | None = None,
               **fields: object) -> None:
        identity = dict(lease_id=None, parent_lease_id=None, uid=None, repo=None,
                        label=None, requested_weight=None, effective_weight=None,
                        wait_seconds=None, outcome=event_type, reason=None)
        if lease is not None:
            identity.update(lease_id=lease.lease_id, uid=lease.uid, repo=lease.repo,
                            label=lease.label, requested_weight=lease.requested_weight,
                            effective_weight=lease.effective_weight,
                            scope_unit=lease.scope_unit)
        identity.update(fields)
        db.execute("INSERT INTO events(timestamp, event_type, payload_json) VALUES (?, ?, ?)",
                   (_now(), event_type, json.dumps(identity, separators=(",", ":"),
                                                  allow_nan=False)))

    def reserve(self, *, uid: int, repo: str, label: str, requested_weight: int,
                capacity: int, wait_seconds: float = 0.0, exclusive: bool = False,
                bypass: bool = False, operator_uid: int | None = None,
                operator_tty: str | None = None, operator_reason: str | None = None,
                signals: object | None = None) -> Lease | None:
        if requested_weight <= 0 or capacity <= 0 or uid < 0 or not repo or not label:
            raise ValueError("invalid lease identity, weight, or capacity")
        if bypass and (operator_uid is None or not operator_tty or not operator_reason):
            raise ValueError("bypass requires authenticated operator audit fields")
        effective = capacity if exclusive else min(requested_weight, capacity)
        with self._transaction() as db:
            used = db.execute("SELECT COALESCE(SUM(effective_weight), 0) FROM leases "
                              "WHERE released_at IS NULL").fetchone()[0]
            if not bypass and (used + effective > capacity or (exclusive and used != 0)):
                self._event(db, "deny", uid=uid, repo=repo, label=label,
                            requested_weight=requested_weight, effective_weight=effective,
                            wait_seconds=wait_seconds, outcome="denied", reason="capacity",
                            signals=signals)
                return None
            lease = Lease(uuid.uuid4().hex, uid, repo, label, requested_weight,
                          effective, exclusive, bypass, None, None, None, None)
            db.execute("INSERT INTO leases(lease_id, uid, repo, label, requested_weight, "
                       "effective_weight, exclusive, bypass, acquired_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (lease.lease_id, uid, repo, label, requested_weight, effective,
                        int(exclusive), int(bypass), _now()))
            audit = dict(wait_seconds=wait_seconds, signals=signals,
                         clamped=requested_weight > capacity or exclusive)
            if bypass:
                audit.update(outcome="admission", operator_uid=operator_uid,
                             operator_tty=operator_tty, operator_reason=operator_reason)
            self._event(db, "bypass" if bypass else "acquire", lease=lease, **audit)
            return lease

    def get_lease(self, lease_id: str) -> Lease | None:
        with self._lock:
            try:
                row = self._db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
            except (AttributeError, sqlite3.Error) as exc:
                raise StoreError(f"cannot read lease: {exc}") from exc
            return self._lease(row) if row else None

    def active_leases(self) -> list[Lease]:
        with self._lock:
            try:
                rows = self._db.execute("SELECT * FROM leases WHERE released_at IS NULL "
                                        "ORDER BY acquired_at, lease_id").fetchall()
            except (AttributeError, sqlite3.Error) as exc:
                raise StoreError(f"cannot read leases: {exc}") from exc
            return [self._lease(row) for row in rows]

    def attach_executor(self, lease_id: str, pid: int) -> None:
        if pid <= 0:
            raise ValueError("executor PID must be positive")
        with self._transaction() as db:
            cursor = db.execute("UPDATE leases SET executor_pid=? WHERE lease_id=? "
                                "AND released_at IS NULL AND executor_pid IS NULL", (pid, lease_id))
            if cursor.rowcount != 1:
                raise StoreError("lease is missing, released, or already has an executor")

    set_executor = attach_executor

    def attach_scope(self, lease_id: str, unit: str, cgroup: str) -> None:
        if not unit or not cgroup:
            raise ValueError("scope identity is required")
        with self._transaction() as db:
            cursor = db.execute("UPDATE leases SET scope_unit=?, scope_cgroup=? "
                                "WHERE lease_id=? AND released_at IS NULL AND scope_unit IS NULL",
                                (unit, cgroup, lease_id))
            if cursor.rowcount != 1:
                raise StoreError("lease is missing, released, or already has a scope")

    def release(self, lease_id: str, *, verified_empty: bool, outcome: str,
                child_exit_code: int | None = None,
                peak_memory_bytes: int | None = None,
                reason: str | None = None) -> None:
        with self._transaction() as db:
            row = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
            if row is None:
                raise StoreError("unknown lease")
            lease = self._lease(row)
            if lease.released_at is not None:
                return
            if not verified_empty:
                raise StoreError("scope emptiness has not been verified")
            self._event(db, "release", lease=lease, outcome=outcome, reason=reason,
                        child_exit_code=child_exit_code,
                        peak_memory_bytes=peak_memory_bytes)
            db.execute("UPDATE leases SET released_at=? WHERE lease_id=?", (_now(), lease_id))

    def recover_unattached(self, lease_id: str, *, executor_gone: bool,
                           unit_absent: bool) -> None:
        with self._transaction() as db:
            row = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
            if row is None:
                raise StoreError("unknown lease")
            lease = self._lease(row)
            if lease.released_at is not None:
                return
            if lease.scope_unit is not None:
                raise StoreError("scope identity exists; verify its cgroup instead")
            if not executor_gone or not unit_absent:
                raise StoreError("unattached reservation cannot be proven empty")
            self._event(db, "release", lease=lease, outcome="infra-error",
                        reason="recovered-unattached")
            db.execute("UPDATE leases SET released_at=? WHERE lease_id=?", (_now(), lease_id))

    def record_event(self, event_type: str, *, lease_id: str | None = None,
                     **fields: object) -> None:
        with self._transaction() as db:
            row = (db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
                   if lease_id else None)
            if lease_id and row is None:
                raise StoreError("unknown lease")
            self._event(db, event_type, lease=self._lease(row) if row else None, **fields)

    def events(self, *, since: str | None = None) -> list[dict[str, object]]:
        with self._lock:
            try:
                sql = "SELECT * FROM events"
                args: tuple[str, ...] = ()
                if since is not None:
                    sql += " WHERE timestamp >= ?"
                    args = (since,)
                rows = self._db.execute(sql + " ORDER BY event_id", args).fetchall()
            except (AttributeError, sqlite3.Error) as exc:
                raise StoreError(f"cannot read events: {exc}") from exc
        return [dict(schema_version=1, event_id=row["event_id"],
                     timestamp=row["timestamp"], event=row["event_type"],
                     **json.loads(row["payload_json"])) for row in rows]

    def events_jsonl(self, *, since: str | None = None) -> str:
        return "".join(json.dumps(event, separators=(",", ":")) + "\n"
                       for event in self.events(since=since))
