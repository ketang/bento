"""Pure-logic tests for capacity policy, config validation, and systemd scope arguments."""

import tempfile
import unittest
from pathlib import Path

from governor import config, scopes

GIB = 1024**3


class CapacityTest(unittest.TestCase):
    def test_observed_host_yields_eight(self):
        self.assertEqual(config.default_capacity(32, 48 * GIB), 8)

    def test_memory_can_be_the_binding_limit(self):
        self.assertEqual(config.default_capacity(64, 24 * GIB), 4)

    def test_small_host_requires_explicit_capacity(self):
        with self.assertRaises(config.ConfigError):
            config.default_capacity(8, 8 * GIB)

    def test_minimum_one_at_twelve_gib(self):
        self.assertEqual(config.default_capacity(2, 12 * GIB), 1)


class ConfigTest(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v1.toml"
            path.write_text(text)
            return config.load(path)

    def test_unknown_key_and_missing_allowlist_rejected(self):
        with self.assertRaises(config.ConfigError):
            self.load("capacity = 2\nallowed_uids=[1]\nbogus = 1\n")
        with self.assertRaises(config.ConfigError):
            self.load("capacity = 2\n")

    def test_valid_config_has_defaults(self):
        loaded = self.load("capacity = 2\nallowed_uids=[1000]\n")
        self.assertEqual((loaded["capacity"], loaded["poll_seconds"], loaded["unit_bytes"]), (2, 10, 4 * GIB))


class ScopeArgsTest(unittest.TestCase):
    def test_transient_unit_sets_memory_limits_and_kill_policy(self):
        args = scopes.start_transient_unit_args("bento-governor-abc.scope", 99, 8 * GIB)
        joined = " ".join(args)
        self.assertIn("StartTransientUnit ssa(sv)a(sa(sv)) bento-governor-abc.scope fail 6", joined)
        self.assertIn(f"MemoryMax t {8 * GIB}", joined)
        self.assertIn("MemorySwapMax t 0", joined)
        self.assertIn("OOMPolicy s kill", joined)
        self.assertIn("PIDs au 1 99", joined)
        self.assertEqual(args[-1], "0")


if __name__ == "__main__":
    unittest.main()
