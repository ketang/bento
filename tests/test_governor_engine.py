"""Deterministic admission-engine tests: fake clock, pressure provider, scope provider, store faults."""

import tempfile
import unittest
from pathlib import Path

from governor.engine import Engine, Request
from governor.store import Store, StoreError


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Handle:
    def __init__(self, lease, pids=()):
        self.executor_pid = 4242
        self.unit = f"bento-{lease.lease_id[:8]}.scope"
        self.cgroup_path = f"/sys/fs/cgroup/system.slice/{self.unit}"
        self.empty, self.oom, self.status, self.peak, self.pids = False, 0, 0, 1 << 30, set(pids)
        self.killed = False

    def is_empty(self): return self.empty
    def oom_kills(self): return self.oom
    def peak_memory(self): return self.peak
    def exit_status(self): return self.status
    def contains_pid(self, pid): return pid in self.pids

    def kill(self):
        self.killed, self.empty, self.status = True, True, -15


class Scopes:
    def __init__(self):
        self.handles, self.fail_launch, self.abort_empty = [], False, True
        self.adoptable, self.executor_is_gone, self.unit_is_absent = {}, True, True

    def launch(self, lease, request):
        if self.fail_launch:
            raise RuntimeError("StartTransientUnit failed")
        handle = Handle(lease, pids={777})
        self.handles.append(handle)
        return handle

    def launch_uncontained(self, lease, request):
        handle = Handle(lease)
        handle.unit = handle.cgroup_path = None
        self.handles.append(handle)
        return handle

    def abort(self, lease):
        handle = Handle(lease)
        handle.empty = self.abort_empty
        return handle

    def release_executor(self, handle): handle.released = True

    def adopt(self, lease): return self.adoptable.get(lease.lease_id)
    def executor_gone(self, lease): return self.executor_is_gone
    def unit_absent(self, lease): return self.unit_is_absent


def ready(*_):
    return {"schema_version": 1, "status": "ready", "signals": []}


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state.sqlite3")
        self.addCleanup(self.store.close)
        self.clock, self.scopes, self.verdict = Clock(), Scopes(), ready
        self.engine = self.make_engine()

    def make_engine(self, authorize=lambda r: True):
        engine = Engine(self.store, {"capacity": 4}, lambda *a: self.verdict(*a), self.scopes,
                        self.clock, authorize)
        engine.reconcile()
        return engine

    def req(self, **kw):
        base = dict(uid=1001, repo="bento", label="build", argv=["true"], cwd="/tmp", weight=2)
        base.update(kw)
        return Request(**base)

    def finish(self, handle, status=0, oom=0):
        handle.empty, handle.status, handle.oom = True, status, oom
        self.engine.poll()

    def outcomes(self):
        return [e["outcome"] for e in self.store.events()]

    def test_weighted_concurrency_and_fifo_no_overtaking(self):
        a, b = self.engine.submit(self.req()), self.engine.submit(self.req())
        big = self.engine.submit(self.req(weight=3))
        small = self.engine.submit(self.req(weight=1))
        self.assertEqual((a.state, b.state, big.state, small.state), ("running",) * 2 + ("queued",) * 2)
        self.finish(self.scopes.handles[0])
        self.assertEqual((a.result["result"]["outcome"], big.state, small.state), ("completed", "queued", "queued"))
        self.finish(self.scopes.handles[1])
        self.assertEqual((big.state, small.state), ("running", "running"))

    def test_clamp_and_exclusive(self):
        clamped = self.engine.submit(self.req(weight=99))
        self.assertEqual(clamped.lease.effective_weight, 4)
        self.assertEqual(clamped.lease.requested_weight, 99)
        exclusive = self.engine.submit(self.req(exclusive=True, weight=1))
        self.assertEqual(exclusive.state, "queued")
        self.finish(self.scopes.handles[0])
        self.assertEqual(exclusive.lease.effective_weight, 4)

    def test_cpu_only_pressure_blocks_and_recovers_on_poll(self):
        self.verdict = lambda *a: {"status": "blocked", "signals": [{"name": "cpu_some_avg10"}]}
        ticket = self.engine.submit(self.req())
        self.assertEqual(ticket.state, "queued")
        self.assertEqual(self.scopes.handles, [])
        self.verdict = ready
        self.engine.poll()
        self.assertEqual(ticket.state, "running")

    def test_max_wait_zero_denies_without_spawn(self):
        self.verdict = lambda *a: {"status": "blocked", "signals": []}
        ticket = self.engine.submit(self.req(max_wait=0))
        self.assertEqual((ticket.exit_code, ticket.result["result"]["outcome"]), (69, "denied"))
        self.assertEqual(self.scopes.handles, [])

    def test_timeout_never_launches(self):
        self.verdict = lambda *a: {"status": "blocked", "signals": []}
        ticket = self.engine.submit(self.req(max_wait=30))
        self.clock.now += 29
        self.engine.poll()
        self.assertEqual(ticket.state, "queued")
        self.clock.now += 1
        self.verdict = ready  # even if pressure clears at the deadline, it must not start
        self.verdict = lambda *a: {"status": "blocked", "signals": []}
        self.engine.poll()
        self.assertEqual((ticket.exit_code, ticket.result["result"]["outcome"]), (75, "timeout"))
        self.assertEqual(ticket.result["result"]["wait_seconds"], 30.0)
        self.assertEqual(self.scopes.handles, [])
        self.assertIn("timeout", self.outcomes())

    def test_missing_signal_fails_closed(self):
        self.verdict = lambda *a: {"status": "error", "signals": []}
        ticket = self.engine.submit(self.req())
        self.assertEqual((ticket.exit_code, self.scopes.handles), (70, []))

    def test_pressure_provider_exception_fails_closed(self):
        def boom(*a): raise OSError("proc gone")
        self.verdict = boom
        self.assertEqual(self.engine.submit(self.req()).exit_code, 70)

    def test_store_fault_before_spawn(self):
        self.store.close()
        with __import__("sqlite3").connect(self.store.path) as db:
            db.execute("CREATE TRIGGER f BEFORE INSERT ON events BEGIN SELECT RAISE(FAIL, 'x'); END")
        self.store = Store(self.store.path)
        self.engine.store = self.store
        ticket = self.engine.submit(self.req())
        self.assertEqual((ticket.exit_code, self.scopes.handles), (70, []))
        self.assertEqual(self.store.active_leases(), [])

    def test_scope_failure_releases_only_when_provably_empty(self):
        self.scopes.fail_launch = True
        ticket = self.engine.submit(self.req())
        self.assertEqual(ticket.exit_code, 70)
        self.assertEqual(self.store.active_leases(), [])
        self.scopes.abort_empty = False
        ticket = self.engine.submit(self.req())
        self.assertEqual(ticket.exit_code, 70)
        self.assertEqual(len(self.store.active_leases()), 1)  # retained, fail closed

    def test_release_after_normal_exit_records_peak_and_status(self):
        ticket = self.engine.submit(self.req())
        handle = self.scopes.handles[0]
        handle.peak = 123
        self.engine.poll()
        self.assertEqual(len(self.store.active_leases()), 1)  # not empty yet
        self.finish(handle, status=3)
        self.assertEqual((ticket.exit_code, ticket.result["result"]["outcome"]), (3, "child-failed"))
        release = self.store.events()[-1]
        self.assertEqual((release["event"], release["peak_memory_bytes"], release["child_exit_code"]),
                         ("release", 123, 3))

    def test_term_forwarded_and_lease_held_until_empty(self):
        ticket = self.engine.submit(self.req())
        self.engine.terminate(ticket)
        self.assertTrue(self.scopes.handles[0].killed)
        self.engine.poll()
        self.assertEqual((ticket.exit_code, self.store.active_leases()), (143, []))

    def test_client_sigkill_keeps_lease_until_scope_empty(self):
        ticket = self.engine.submit(self.req())
        self.engine.cancel(ticket)
        self.assertIn("client-lost", self.outcomes())
        self.assertEqual(len(self.store.active_leases()), 1)
        self.finish(self.scopes.handles[0])
        self.assertEqual(self.store.active_leases(), [])

    def test_disconnect_cancels_queued_request_without_launch(self):
        self.engine.submit(self.req(weight=4))
        waiting = self.engine.submit(self.req())
        self.engine.cancel(waiting)
        self.finish(self.scopes.handles[0])
        self.assertEqual(len(self.scopes.handles), 1)

    def test_oom_with_wrapper_exit_zero(self):
        ticket = self.engine.submit(self.req())
        self.finish(self.scopes.handles[0], status=0, oom=1)
        self.assertEqual((ticket.exit_code, ticket.result["result"]["outcome"]), (137, "oom-killed"))

    def test_unreadable_oom_result_is_infra_error(self):
        ticket = self.engine.submit(self.req())
        handle = self.scopes.handles[0]
        handle.oom_kills = lambda: None
        self.finish(handle)
        self.assertEqual(ticket.exit_code, 70)

    def test_nested_call_verified_by_cgroup_membership(self):
        outer = self.engine.submit(self.req())
        token = outer.token
        inner = self.engine.submit(self.req(weight=1, parent_token=token, peer_pid=777))
        self.assertEqual((inner.state, len(self.store.active_leases())), ("running", 1))
        self.assertEqual(self.store.events()[-1]["parent_lease_id"], outer.lease.lease_id)
        copied = self.engine.submit(self.req(weight=1, parent_token=token, peer_pid=999))
        self.assertEqual(len(self.store.active_leases()), 2)  # treated as an ordinary request
        self.assertEqual(copied.state, "running")

    def test_nested_larger_or_exclusive_denied(self):
        outer = self.engine.submit(self.req())
        big = self.engine.submit(self.req(weight=3, parent_token=outer.token, peer_pid=777))
        excl = self.engine.submit(self.req(exclusive=True, parent_token=outer.token, peer_pid=777))
        self.assertEqual((big.exit_code, excl.exit_code), (69, 69))

    def test_bypass_admission_requires_authorization_and_audits(self):
        self.engine = self.make_engine(authorize=lambda r: False)
        denied = self.engine.submit(self.req(bypass="admission", reason="ticket"))
        self.assertEqual(denied.exit_code, 69)
        self.engine = self.make_engine()
        self.engine.submit(self.req(weight=4))
        self.verdict = lambda *a: {"status": "blocked", "signals": []}
        bypass = self.engine.submit(self.req(bypass="admission", reason="ticket", operator_uid=0,
                                             operator_tty="/dev/pts/1"))
        self.assertEqual(bypass.state, "running")
        event = [e for e in self.store.events() if e["event"] == "bypass"][0]
        self.assertEqual((event["outcome"], event["operator_reason"], event["operator_tty"]),
                         ("admission", "ticket", "/dev/pts/1"))

    def test_bypass_uncontained_logged_before_start_without_scope(self):
        ticket = self.engine.submit(self.req(bypass="uncontained", reason="no systemd", operator_uid=0, operator_tty="/dev/pts/2"))
        self.assertEqual(ticket.state, "running")
        self.assertEqual(self.store.events()[-1]["outcome"], "uncontained")
        self.assertIsNone(self.store.active_leases()[0].scope_unit)

    def test_bypass_fails_closed_when_audit_store_broken(self):
        self.store.close()
        with __import__("sqlite3").connect(self.store.path) as db:
            db.execute("CREATE TRIGGER f BEFORE INSERT ON events BEGIN SELECT RAISE(FAIL, 'x'); END")
        self.store = Store(self.store.path)
        self.engine.store = self.store
        ticket = self.engine.submit(self.req(bypass="uncontained", reason="r", operator_uid=0, operator_tty="/dev/pts/2"))
        self.assertEqual((ticket.exit_code, self.scopes.handles), (70, []))

    def test_restart_reconciles_scopes_and_blocks_on_unverifiable(self):
        held = self.engine.submit(self.req(weight=2))
        lost = self.engine.submit(self.req(weight=2))
        lease_ids = [held.lease.lease_id, lost.lease.lease_id]
        restarted = Engine(self.store, {"capacity": 4}, ready, self.scopes, self.clock)
        self.scopes.adoptable[lease_ids[0]] = self.scopes.handles[0]
        unresolved = restarted.reconcile()
        self.assertEqual(unresolved, [lease_ids[1]])
        blocked = restarted.submit(self.req(weight=1))
        self.assertEqual(blocked.exit_code, 70)  # admission stays closed
        self.assertEqual(len(self.store.active_leases()), 2)
        self.scopes.adoptable[lease_ids[1]] = self.scopes.handles[1]
        self.assertEqual(restarted.reconcile(), [])
        for handle in self.scopes.handles[:2]:
            handle.empty = True
        restarted.poll()
        self.assertEqual(self.store.active_leases(), [])

    def test_unattached_reservation_recovered_only_with_proof(self):
        lease = self.store.reserve(uid=1, repo="r", label="l", requested_weight=1, capacity=4, wait_seconds=0)
        self.scopes.unit_is_absent = False
        engine = Engine(self.store, {"capacity": 4}, ready, self.scopes, self.clock)
        self.assertEqual(engine.reconcile(), [lease.lease_id])
        self.scopes.unit_is_absent = True
        self.assertEqual(engine.reconcile(), [])
        self.assertEqual(self.store.active_leases(), [])


if __name__ == "__main__":
    unittest.main()
