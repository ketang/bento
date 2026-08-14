"""Tests for scripts/run-tests-with-skip-policy.py (bento-qi34)."""

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run-tests-with-skip-policy.py"


def load_module():
    loader = importlib.machinery.SourceFileLoader("run_tests_with_skip_policy", str(SCRIPT))
    spec = importlib.util.spec_from_loader("run_tests_with_skip_policy", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for run-tests-with-skip-policy.py")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class DiffSkipsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()
        # A full actual-skips dict that exactly satisfies EXPECTED_SKIPS,
        # using an arbitrary acceptable reason per test id. Tests mutate a
        # copy of this baseline so each assertion isolates one dimension of
        # the diff instead of also tripping "expected skip did not occur".
        self.baseline = {
            test_id: next(iter(reasons))
            for test_id, reasons in self.mod.EXPECTED_SKIPS.items()
        }

    def test_expected_skip_with_any_acceptable_reason_matches(self) -> None:
        test_id = next(iter(self.mod.EXPECTED_SKIPS))
        for reason in self.mod.EXPECTED_SKIPS[test_id]:
            with self.subTest(reason=reason):
                actual = dict(self.baseline)
                actual[test_id] = reason
                self.assertEqual(self.mod._diff_skips(actual), [])

    def test_nested_agent_session_reason_is_acceptable_when_cli_reason_is_also_registered(
        self,
    ) -> None:
        # bento-qi34: e2e tests skip with the "must both be on PATH" reason
        # when the CLI is missing, but with the nested-agent-session reason
        # when an agent runs the suite with the CLI present. Both must match.
        e2e_id = (
            "tests.bento_auto_allow.test_auto_allow_e2e."
            "AutoAllowHookE2ETest.test_allows_plugin_script"
        )
        actual = dict(self.baseline)
        actual[e2e_id] = self.mod._NESTED_AGENT_SESSION_REASON
        self.assertEqual(self.mod._diff_skips(actual), [])

    def test_doc_claims_word_budget_skip_is_registered(self) -> None:
        # bento-qi34: this skip was previously absent from EXPECTED_SKIPS. A
        # bare assertIn would pass even if the registered reason were wrong,
        # so also check it matches the source-of-truth constant.
        from tests.test_doc_claims import BeadsCodexBlockStaysMinimal

        test_id = (
            "tests.test_doc_claims.BeadsCodexBlockStaysMinimal.test_block_under_word_budget"
        )
        self.assertIn(test_id, self.mod.EXPECTED_SKIPS)
        self.assertIn(
            BeadsCodexBlockStaysMinimal.SKIP_REASON, self.mod.EXPECTED_SKIPS[test_id]
        )

    def test_unknown_test_id_is_reported(self) -> None:
        actual = dict(self.baseline)
        actual["tests.unknown.Thing.test_x"] = "some reason"
        problems = self.mod._diff_skips(actual)
        self.assertEqual(len(problems), 1)
        self.assertIn("unexpected skip", problems[0])

    def test_unrecognized_reason_for_known_test_id_is_reported(self) -> None:
        test_id = next(iter(self.mod.EXPECTED_SKIPS))
        actual = dict(self.baseline)
        actual[test_id] = "some made up reason"
        problems = self.mod._diff_skips(actual)
        self.assertEqual(len(problems), 1)
        self.assertIn("unrecognized skip reason", problems[0])

    def test_missing_expected_skip_is_reported(self) -> None:
        problems = self.mod._diff_skips({})
        self.assertEqual(len(problems), len(self.mod.EXPECTED_SKIPS))
        for problem in problems:
            self.assertIn("expected skip did not occur", problem)

    def test_exact_expected_set_has_no_problems(self) -> None:
        self.assertEqual(self.mod._diff_skips(self.baseline), [])

    def test_nested_agent_session_reason_matches_e2e_utils_source_of_truth(self) -> None:
        # bento-qi34 finding 2: the reason is imported, not hand-copied, so
        # this passes by construction -- guards against a future refactor
        # reintroducing a hand-copied duplicate that can silently drift.
        from tests.e2e_utils import NESTED_AGENT_SESSION_SKIP_REASON

        self.assertEqual(self.mod._NESTED_AGENT_SESSION_REASON, NESTED_AGENT_SESSION_SKIP_REASON)

    def test_swarm_codex_integration_setup_skip_reason_is_registered(self) -> None:
        # bento-qi34 finding 3: this test has two skip paths -- the class
        # decorator (RUN_CODEX_INTEGRATION unset) and a setUp() skipTest when
        # the codex CLI is missing. Both reasons must be registered or the
        # gate fails closed with RUN_CODEX_INTEGRATION=1 set but no codex CLI.
        test_id = (
            "tests.swarm.test_swarm_codex_integration."
            "SwarmCodexIntegrationTest.test_codex_exec_resume_preserves_thread_id_and_state_root"
        )
        self.assertIn("codex CLI not installed", self.mod.EXPECTED_SKIPS[test_id])


if __name__ == "__main__":
    unittest.main()
