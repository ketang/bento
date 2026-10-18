"""Durability and admission invariants for the host governor store."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from governor.store import Store, StoreError


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)

    def reserve(self, **overrides):
        args = dict(uid=1001, repo="bento", label="build", requested_weight=2,
                    capacity=4, wait_seconds=0.25)
        args.update(overrides)
        return self.store.reserve(**args)

    def test_wal_full_and_atomic_weighted_capacity(self):
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 2)
        first = self.reserve()
        second = self.reserve()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(self.reserve())
        self.assertEqual(sum(x.effective_weight for x in self.store.active_leases()), 4)
        self.assertEqual([e["outcome"] for e in self.store.events()], ["acquire", "acquire", "denied"])

    def test_clamp_exclusive_and_bypass_overcapacity(self):
        first = self.reserve(requested_weight=99)
        self.assertEqual(first.effective_weight, 4)
        self.assertEqual(first.requested_weight, 99)
        self.assertIsNone(self.reserve(exclusive=True))
        self.store.release(first.lease_id, verified_empty=True, outcome="completed", child_exit_code=0,
                           peak_memory_bytes=123)
        exclusive = self.reserve(exclusive=True, requested_weight=1)
        self.assertEqual(exclusive.effective_weight, 4)
        self.assertIsNone(self.reserve(requested_weight=1))
        bypass = self.reserve(requested_weight=3, bypass=True, operator_uid=0,
                              operator_tty="/dev/pts/1", operator_reason="emergency ticket")
        self.assertEqual(sum(x.effective_weight for x in self.store.active_leases()), 7)
        self.assertIsNone(self.reserve(requested_weight=1))
        self.assertEqual(self.store.events()[-2]["outcome"], "admission")

    def test_scope_identity_and_release_require_verified_empty(self):
        lease = self.reserve()
        self.store.attach_executor(lease.lease_id, 12345)
        self.store.attach_scope(lease.lease_id, "bento-123.scope", "/sys/fs/cgroup/system.slice/bento-123.scope")
        with self.assertRaises(StoreError):
            self.store.release(lease.lease_id, verified_empty=False, outcome="completed")
        self.assertEqual(len(self.store.active_leases()), 1)
        self.store.release(lease.lease_id, verified_empty=True, outcome="completed",
                           child_exit_code=0, peak_memory_bytes=2048)
        self.assertEqual(self.store.active_leases(), [])
        event = self.store.events()[-1]
        self.assertEqual((event["scope_unit"], event["peak_memory_bytes"], event["child_exit_code"]),
                         ("bento-123.scope", 2048, 0))

    def test_restart_and_unattached_recovery_fail_closed(self):
        lease = self.reserve()
        self.store.attach_executor(lease.lease_id, 12345)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.active_leases()[0].lease_id, lease.lease_id)
        with self.assertRaises(StoreError):
            self.store.recover_unattached(lease.lease_id, executor_gone=True, unit_absent=False)
        self.assertEqual(len(self.store.active_leases()), 1)
        self.store.recover_unattached(lease.lease_id, executor_gone=True, unit_absent=True)
        self.assertEqual(self.store.active_leases(), [])

    def test_events_jsonl_and_since(self):
        lease = self.reserve()
        self.store.record_event("client-lost", lease_id=lease.lease_id, outcome="client-lost")
        events = self.store.events()
        self.assertEqual([e["event_id"] for e in events], [1, 2])
        self.assertEqual([json.loads(line) for line in self.store.events_jsonl().splitlines()], events)
        self.assertEqual(self.store.events(since=events[1]["timestamp"])[-1]["event_id"], 2)

    def test_audit_failure_rolls_back_reservation(self):
        self.store.close()
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(FAIL, 'audit failed'); END")
        self.store = Store(self.path)
        with self.assertRaises(StoreError):
            self.reserve()
        self.assertEqual(self.store.active_leases(), [])

    def test_capacity_serializes_across_store_connections(self):
        second_store = Store(self.path)
        self.addCleanup(second_store.close)
        self.assertIsNotNone(self.reserve(requested_weight=3))
        self.assertIsNone(second_store.reserve(uid=1002, repo="shatter", label="build",
                                                requested_weight=2, capacity=4))
        self.assertEqual(len(second_store.active_leases()), 1)

    def test_release_audit_failure_preserves_reservation(self):
        lease = self.reserve()
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TRIGGER fail_release BEFORE INSERT ON events "
                               "WHEN NEW.event_type = 'release' "
                               "BEGIN SELECT RAISE(FAIL, 'audit failed'); END")
        with self.assertRaises(StoreError):
            self.store.release(lease.lease_id, verified_empty=True, outcome="completed")
        self.assertEqual(self.store.get_lease(lease.lease_id).released_at, None)


if __name__ == "__main__":
    unittest.main()
