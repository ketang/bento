"""Admission engine: FIFO queue, fail-closed pressure gating, scope lifecycle, reconciliation.

All host interaction goes through injected providers so behavior is deterministic in tests:
  pressure(weight, exclusive, cwd, env) -> schema-v1 snapshot dict (see governor.pressure)
  scopes: launch(lease, request) -> handle; release_executor(handle); adopt(lease) -> handle | None; abort(lease) -> handle | None;
          executor_gone(lease) -> bool; unit_absent(lease) -> bool
  handle: unit, cgroup_path, is_empty(), oom_kills(), peak_memory(), exit_status(), kill(), contains_pid(pid)
  authorize_bypass(request) -> bool
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any, Callable

from . import CONTRACT_VERSION
from .store import Lease, Store, StoreError

EXIT = {"invalid-args": 64, "denied": 69, "infra-error": 70, "timeout": 75, "oom-killed": 137}


@dataclass
class Request:
    uid: int
    repo: str
    label: str
    argv: list[str]
    cwd: str
    env: dict[str, str] = field(default_factory=dict)
    weight: int = 1
    exclusive: bool = False
    max_wait: float | None = None
    bypass: str | None = None
    reason: str | None = None
    operator_uid: int | None = None
    operator_tty: str | None = None
    peer_pid: int | None = None
    gid: int = 0
    parent_token: str | None = None


@dataclass
class Ticket:
    request: Request
    enqueued_at: float
    state: str = "queued"  # queued | running | done
    result: dict[str, Any] | None = None
    lease: Lease | None = None
    handle: Any = None
    token: str | None = None
    client_lost: bool = False
    terminated: bool = False

    @property
    def exit_code(self) -> int | None:
        return None if self.result is None else self.result["exit_code"]


class Engine:
    def __init__(self, store: Store, config: dict, pressure: Callable, scopes: Any,
                 clock: Callable[[], float], authorize_bypass: Callable[[Request], bool] = lambda r: False):
        self.store, self.config, self.pressure, self.scopes = store, config, pressure, scopes
        self.clock, self.authorize_bypass = clock, authorize_bypass
        self.capacity: int = config["capacity"]
        self.queue: list[Ticket] = []
        self.running: dict[str, Ticket] = {}
        self.admitting = False  # opened only after reconcile() proves every lease

    # -- results ---------------------------------------------------------------------------
    def _finish(self, ticket: Ticket, outcome: str, *, exit_code: int | None = None,
                child_exit_code: int | None = None, detail: str | None = None) -> None:
        lease_id = ticket.lease.lease_id if ticket.lease else None
        result = {"schema_version": CONTRACT_VERSION, "outcome": outcome, "lease_id": lease_id,
                  "wait_seconds": round(self._wait(ticket), 3), "child_exit_code": child_exit_code}
        if detail:
            result["detail"] = detail
        ticket.result = {"exit_code": EXIT.get(outcome, 70) if exit_code is None else exit_code,
                         "result": result}
        ticket.state = "done"

    def _wait(self, ticket: Ticket) -> float:
        return self.clock() - ticket.enqueued_at

    def _identity(self, req: Request, wait: float) -> dict[str, Any]:
        return dict(uid=req.uid, repo=req.repo, label=req.label, requested_weight=req.weight,
                    effective_weight=self.capacity if req.exclusive else min(req.weight, self.capacity),
                    wait_seconds=round(wait, 3))

    def _audit(self, kind: str, ticket: Ticket, outcome: str, reason: str, signals: Any = None) -> bool:
        try:
            self.store.record_event(kind, outcome=outcome, reason=reason, signals=signals,
                                    **self._identity(ticket.request, self._wait(ticket)))
            return True
        except StoreError:
            return False

    # -- submission ------------------------------------------------------------------------
    def submit(self, req: Request) -> Ticket:
        ticket = Ticket(req, self.clock())
        if req.weight < 1 or (req.max_wait is not None and req.max_wait < 0):
            self._finish(ticket, "invalid-args", detail="invalid weight or max-wait")
            return ticket
        if req.bypass and not (req.operator_uid is not None and req.operator_tty and (req.reason or "").strip()
                               and self.authorize_bypass(req)):
            self._audit("deny", ticket, "denied", "bypass-not-authorized")
            self._finish(ticket, "denied", detail="bypass not authorized")
            return ticket
        if req.parent_token and self._nested(ticket):
            return ticket
        self.queue.append(ticket)
        self.poll()
        return ticket

    def _nested(self, ticket: Ticket) -> bool:
        """Handle a re-entrant call. Returns True if the ticket is finished or granted."""
        req = ticket.request
        outer = self.running.get(req.parent_token or "")
        if outer is None or outer.state != "running" or outer.handle is None:
            return False  # unknown/stale token: an ordinary request, never re-entrant
        if req.peer_pid is None or not outer.handle.contains_pid(req.peer_pid):
            return False  # copied token from outside the live scope
        parent = outer.lease
        if req.exclusive or req.weight > parent.effective_weight:
            self._audit("deny", ticket, "denied", "nested-exceeds-outer")
            self._finish(ticket, "denied", detail="nested weight exceeds outer lease")
            return True
        try:
            self.store.record_event("acquire", outcome="nested", parent_lease_id=parent.lease_id,
                                    **self._identity(req, 0.0))
        except StoreError as exc:
            self._finish(ticket, "infra-error", detail=str(exc))
            return True
        ticket.lease, ticket.handle, ticket.state = parent, outer.handle, "running"
        ticket.token = None
        return True

    def cancel(self, ticket: Ticket) -> None:
        """Client connection lost."""
        if ticket.state == "queued":
            self.queue.remove(ticket)
            self._finish(ticket, "infra-error", detail="client disconnected before admission")
            return
        if ticket.state == "running" and not ticket.client_lost and ticket.token:
            ticket.client_lost = True
            try:
                self.store.record_event("client-lost", lease_id=ticket.lease.lease_id,
                                        outcome="client-lost")
            except StoreError:
                pass

    def terminate(self, ticket: Ticket) -> None:
        """SIGINT/SIGTERM forwarded from the client: signal the scope, keep the lease until empty."""
        if ticket.state == "running" and ticket.handle is not None:
            ticket.terminated = True
            ticket.handle.kill()

    # -- main loop -------------------------------------------------------------------------
    def poll(self) -> None:
        self._reap()
        if not self.admitting:
            for ticket in list(self.queue):
                self.queue.remove(ticket)
                self._finish(ticket, "infra-error", detail="governor is reconciling leases")
            return
        self._expire()
        while self.queue and self._admit(self.queue[0]):
            pass

    def _reap(self) -> None:
        for token, ticket in list(self.running.items()):
            handle = ticket.handle
            if not handle.is_empty():
                continue
            oom = handle.oom_kills() is None or handle.oom_kills() > 0
            status = handle.exit_status()
            outcome = ("oom-killed" if oom else
                       "completed" if status == 0 else "child-failed")
            if handle.oom_kills() is None:
                outcome = "infra-error"
            try:
                self.store.release(ticket.lease.lease_id, verified_empty=True, outcome=outcome,
                                   child_exit_code=status, peak_memory_bytes=handle.peak_memory())
            except StoreError:
                continue  # keep reserved; retried on the next poll
            del self.running[token]
            if outcome == "oom-killed":
                self._finish(ticket, outcome, exit_code=137, child_exit_code=status)
            elif outcome == "infra-error":
                self._finish(ticket, outcome, child_exit_code=status, detail="OOM result unavailable")
            elif ticket.terminated and status is not None and status < 0:
                self._finish(ticket, outcome, exit_code=128 - status, child_exit_code=status)
            else:
                self._finish(ticket, outcome, exit_code=status if status is not None else 70,
                             child_exit_code=status)

    def _expire(self) -> None:
        now = self.clock()
        for ticket in list(self.queue):
            wait = ticket.request.max_wait
            if wait and now - ticket.enqueued_at >= wait and ticket is not self.queue[0]:
                self.queue.remove(ticket)
                self._audit("timeout", ticket, "timeout", "max-wait")
                self._finish(ticket, "timeout")

    def _blocked(self, ticket: Ticket, reason: str, signals: Any) -> bool:
        """Head cannot run now. Returns True if the ticket left the queue."""
        wait = ticket.request.max_wait
        if wait == 0:
            outcome, kind = "denied", "deny"
        elif wait is not None and self._wait(ticket) >= wait:
            outcome, kind = "timeout", "timeout"
        else:
            return False
        self.queue.remove(ticket)
        self._audit(kind, ticket, outcome, reason, signals)
        self._finish(ticket, outcome, detail=reason)
        return True

    def _admit(self, ticket: Ticket) -> bool:
        """Try to start the queue head. Returns True if the queue head was consumed."""
        req = ticket.request
        if req.bypass == "uncontained":
            return self._launch(ticket, bypass=True, signals=None)
        signals = None
        if req.bypass != "admission":
            try:
                signals = self.pressure(req.weight, req.exclusive, req.cwd, req.env)
            except Exception as exc:  # pressure provider failure is an infrastructure error
                signals = {"status": "error", "signals": [], "detail": str(exc)}
            if signals["status"] == "error":
                self.queue.remove(ticket)
                self._audit("infra-error", ticket, "infra-error", "signal-error", signals)
                self._finish(ticket, "infra-error", detail="required signal unavailable")
                return True
            if signals["status"] == "blocked":
                return self._blocked(ticket, "pressure", signals)
        return self._launch(ticket, bypass=req.bypass == "admission", signals=signals)

    def _launch(self, ticket: Ticket, *, bypass: bool, signals: Any) -> bool:
        req = ticket.request
        try:
            lease = self.store.reserve(
                uid=req.uid, repo=req.repo, label=req.label, requested_weight=req.weight,
                capacity=self.capacity, wait_seconds=round(self._wait(ticket), 3),
                exclusive=req.exclusive, bypass=bypass, signals=signals,
                operator_uid=req.operator_uid, operator_tty=req.operator_tty, operator_reason=req.reason)
        except (StoreError, ValueError) as exc:
            self.queue.remove(ticket)
            self._finish(ticket, "infra-error", detail=str(exc))
            return True
        if lease is None:
            return self._blocked(ticket, "capacity", signals)
        if req.bypass == "uncontained":
            try:  # durable, before any command starts
                self.store.record_event("bypass", lease_id=lease.lease_id, outcome="uncontained",
                                        operator_uid=req.operator_uid, operator_tty=req.operator_tty,
                                        operator_reason=req.reason)
            except StoreError as exc:
                self.queue.remove(ticket)
                ticket.lease = lease
                self._abort_reserved_only(ticket, str(exc))
                return True
        self.queue.remove(ticket)
        ticket.lease = lease
        try:
            launch = self.scopes.launch_uncontained if req.bypass == "uncontained" else self.scopes.launch
            handle = launch(lease, req)
            self.store.attach_executor(lease.lease_id, handle.executor_pid)
            if handle.unit is not None:
                self.store.attach_scope(lease.lease_id, handle.unit, handle.cgroup_path)
            self.scopes.release_executor(handle)  # only now may the command exec
        except Exception as exc:
            self._abort(ticket, str(exc))
            return True
        ticket.handle, ticket.state = handle, "running"
        ticket.token = secrets.token_hex(16)
        self.running[ticket.token] = ticket
        return True

    def _abort_reserved_only(self, ticket: Ticket, detail: str) -> None:
        """Audit failed before any process existed: release the never-used reservation if possible."""
        try:
            self.store.release(ticket.lease.lease_id, verified_empty=True, outcome="infra-error",
                               reason="audit-failed")
        except StoreError:
            pass  # stays reserved; recovery will prove it unattached
        self._finish(ticket, "infra-error", detail=detail)

    def _abort(self, ticket: Ticket, detail: str) -> None:
        lease = ticket.lease
        handle = None
        try:
            handle = self.scopes.abort(lease)
        except Exception:
            pass
        if handle is not None and handle.is_empty():
            try:
                self.store.release(lease.lease_id, verified_empty=True, outcome="infra-error",
                                   reason="launch-failed", peak_memory_bytes=handle.peak_memory())
            except StoreError:
                pass
            else:
                self._finish(ticket, "infra-error", detail=detail)
                return
        # emptiness unproven: keep the reservation and fail closed
        self._finish(ticket, "infra-error", detail=detail + " (lease retained for operator repair)")

    # -- restart reconciliation -----------------------------------------------------------
    def reconcile(self) -> list[str]:
        """Verify every durable lease before opening admission. Returns unverifiable lease ids."""
        unresolved = []
        for lease in self.store.active_leases():
            if lease.scope_unit is None:
                try:
                    self.store.recover_unattached(
                        lease.lease_id, executor_gone=self.scopes.executor_gone(lease),
                        unit_absent=self.scopes.unit_absent(lease))
                except StoreError:
                    unresolved.append(lease.lease_id)
                continue
            handle = self.scopes.adopt(lease)
            if handle is None:
                unresolved.append(lease.lease_id)
                continue
            ticket = Ticket(Request(lease.uid, lease.repo, lease.label, [], ""), self.clock(),
                            state="running", lease=lease, handle=handle, client_lost=True)
            self.running[secrets.token_hex(16)] = ticket
        self.admitting = not unresolved
        self._reap()
        return unresolved
