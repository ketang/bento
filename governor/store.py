"""Durable lease registry and append-only event log (SQLite, WAL, synchronous=FULL)."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import CONTRACT_VERSION

SCHEMA = """
CREATE TABLE IF NOT EXISTS leases (
    lease_id TEXT PRIMARY KEY,
    parent_lease_id TEXT,
    uid INTEGER NOT NULL,
    repo TEXT NOT NULL,
    label TEXT NOT NULL,
    requested_weight INTEGER NOT NULL,
    effective_weight INTEGER NOT NULL,
    wait_seconds REAL NOT NULL,
    bypass TEXT,
    executor_pid INTEGER,
    scope_unit TEXT,
    cgroup_path TEXT
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    kind TEXT NOT NULL,
    lease_id TEXT,
    parent_lease_id TEXT,
    uid INTEGER,
    repo TEXT,
    label TEXT,
    requested_weight INTEGER,
    effective_weight INTEGER,
    wait_seconds REAL,
    outcome TEXT,
    reason TEXT,
    scope_unit TEXT,
    peak_memory_bytes INTEGER,
    signals TEXT,
    child_exit_code INTEGER,
    operator_uid INTEGER,
    operator_tty TEXT,
    operator_reason TEXT
);
"""

EVENT_FIELDS = (
    "lease_id", "parent_lease_id", "uid", "repo", "label", "requested_weight", "effective_weight",
    "wait_seconds", "outcome", "reason", "scope_unit", "peak_memory_bytes", "signals",
    "child_exit_code", "operator_uid", "operator_tty", "operator_reason",
)


class StoreError(Exception):
    """The state or audit store cannot safely record a decision."""


@dataclass(frozen=True)
class Lease:
    lease_id: str
    parent_lease_id: str | None
    uid: int
    repo: str
    label: str
    requested_weight: int
    effective_weight: int
    wait_seconds: float
    bypass: str | None
    executor_pid: int | None
    scope_unit: str | None
    cgroup_path: str | None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        try:
            self._db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
            self._db.row_factory = sqlite3.Row
            if self._db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
                raise StoreError("cannot enable WAL journaling")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise StoreError(f"cannot open state store {self.path}: {exc}") from exc

    def close(self) -> None:
        with contextlib.suppress(sqlite3.Error):
            self._db.close()

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            self._db.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise StoreError(f"cannot begin transaction: {exc}") from exc
        try:
            yield self._db
            self._db.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                self._db.execute("ROLLBACK")
            raise StoreError(f"state store failure: {exc}") from exc
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                self._db.execute("ROLLBACK")
            raise

    @staticmethod
    def _insert_event(db: sqlite3.Connection, kind: str, **fields: Any) -> None:
        unknown = set(fields) - set(EVENT_FIELDS)
        if unknown:
            raise StoreError(f"unknown event fields: {sorted(unknown)}")
        if isinstance(fields.get("signals"), (dict, list)):
            fields["signals"] = json.dumps(fields["signals"], separators=(",", ":"))
        columns = ["timestamp", "kind", *fields]
        db.execute(
            f"INSERT INTO events ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            [_now(), kind, *fields.values()],
        )

    @staticmethod
    def _lease(row: sqlite3.Row) -> Lease:
        return Lease(**{name: row[name] for name in Lease.__dataclass_fields__})

    @staticmethod
    def _identity(lease: sqlite3.Row) -> dict[str, Any]:
        return {name: lease[name] for name in (
            "lease_id", "parent_lease_id", "uid", "repo", "label", "requested_weight",
            "effective_weight", "wait_seconds", "scope_unit")}

    def active_leases(self) -> list[Lease]:
        try:
            rows = self._db.execute("SELECT * FROM leases ORDER BY rowid").fetchall()
        except sqlite3.Error as exc:
            raise StoreError(str(exc)) from exc
        return [self._lease(row) for row in rows]

    def reserve(self, *, uid: int, repo: str, label: str, requested_weight: int, capacity: int,
                wait_seconds: float, exclusive: bool = False, bypass: bool = False,
                parent_lease_id: str | None = None, signals: Any = None,
                operator_uid: int | None = None, operator_tty: str | None = None,
                operator_reason: str | None = None) -> Lease | None:
        """Atomically reserve weight and commit the acquire event, or record a denial."""
        effective = capacity if exclusive else min(requested_weight, capacity)
        if effective < 1:
            raise StoreError("effective weight must be positive")
        identity = dict(uid=uid, repo=repo, label=label, requested_weight=requested_weight,
                        effective_weight=effective, wait_seconds=wait_seconds,
                        parent_lease_id=parent_lease_id, signals=signals)
        with self._transaction() as db:
            used = db.execute("SELECT COALESCE(SUM(effective_weight), 0) FROM leases").fetchone()[0]
            if not bypass and used + effective > capacity:
                self._insert_event(db, "deny", outcome="denied", reason="capacity", **identity)
                return None
            lease_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO leases (lease_id, parent_lease_id, uid, repo, label, requested_weight,"
                " effective_weight, wait_seconds, bypass) VALUES (?,?,?,?,?,?,?,?,?)",
                (lease_id, parent_lease_id, uid, repo, label, requested_weight, effective,
                 wait_seconds, "admission" if bypass else None))
            if bypass:
                self._insert_event(db, "bypass", lease_id=lease_id, outcome="admission",
                                   operator_uid=operator_uid, operator_tty=operator_tty,
                                   operator_reason=operator_reason, **identity)
            else:
                self._insert_event(db, "acquire", lease_id=lease_id, outcome="acquire", **identity)
            row = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
        return self._lease(row)

    def attach_executor(self, lease_id: str, pid: int) -> None:
        with self._transaction() as db:
            self._require(db, lease_id)
            db.execute("UPDATE leases SET executor_pid=? WHERE lease_id=?", (pid, lease_id))

    def attach_scope(self, lease_id: str, unit: str, cgroup_path: str) -> None:
        with self._transaction() as db:
            self._require(db, lease_id)
            db.execute("UPDATE leases SET scope_unit=?, cgroup_path=? WHERE lease_id=?",
                       (unit, cgroup_path, lease_id))

    @staticmethod
    def _require(db: sqlite3.Connection, lease_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
        if row is None:
            raise StoreError(f"unknown or already released lease {lease_id}")
        return row

    def release(self, lease_id: str, *, verified_empty: bool, outcome: str,
                child_exit_code: int | None = None, peak_memory_bytes: int | None = None,
                reason: str | None = None) -> None:
        """Free a lease. Refuses unless the caller has proven the scope cgroup is empty."""
        if not verified_empty:
            raise StoreError("refusing to release a lease whose scope is not verified empty")
        with self._transaction() as db:
            lease = self._require(db, lease_id)
            self._insert_event(db, "release", outcome=outcome, reason=reason,
                               child_exit_code=child_exit_code,
                               peak_memory_bytes=peak_memory_bytes, **self._identity(lease))
            db.execute("DELETE FROM leases WHERE lease_id=?", (lease_id,))

    def recover_unattached(self, lease_id: str, *, executor_gone: bool, unit_absent: bool) -> None:
        """Release a reservation that never got a persisted scope, only with proof of absence."""
        with self._transaction() as db:
            lease = self._require(db, lease_id)
            if lease["scope_unit"] is not None:
                raise StoreError("lease has a persisted scope; reconcile the scope instead")
            if not (executor_gone and unit_absent):
                raise StoreError("cannot prove the executor and scope unit are gone; lease stays reserved")
            self._insert_event(db, "release", outcome="recovered", reason="unattached-recovery",
                               **self._identity(lease))
            db.execute("DELETE FROM leases WHERE lease_id=?", (lease_id,))

    def record_event(self, kind: str, *, lease_id: str | None = None, **fields: Any) -> None:
        with self._transaction() as db:
            if lease_id is not None:
                lease = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
                if lease is not None:
                    fields = {**self._identity(lease), **fields}
                else:
                    fields["lease_id"] = lease_id
            self._insert_event(db, kind, **fields)

    def events(self, since: str | None = None) -> list[dict[str, Any]]:
        query, args = "SELECT * FROM events", []
        if since:
            query += " WHERE timestamp >= ?"
            args.append(since)
        try:
            rows = self._db.execute(query + " ORDER BY event_id", args).fetchall()
        except sqlite3.Error as exc:
            raise StoreError(str(exc)) from exc
        result = []
        for row in rows:
            event = {"schema_version": CONTRACT_VERSION, **dict(row)}
            event["event"] = event.pop("kind")
            if event["signals"] is not None:
                event["signals"] = json.loads(event["signals"])
            result.append(event)
        return result

    def events_jsonl(self, since: str | None = None) -> str:
        return "".join(json.dumps(e, separators=(",", ":"), sort_keys=True) + "\n"
                       for e in self.events(since))
