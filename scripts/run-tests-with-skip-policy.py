#!/usr/bin/env python3
"""Run the full unittest suite and fail if the set of skipped tests drifts.

A skip is only acceptable when its test id is already in EXPECTED_SKIPS and
its reason is one of that test id's acceptable reasons. This catches a test
silently starting to skip (broken env, missing dependency) as well as a new
skip nobody added to the allowlist. Reasons are a set, not a single string,
because some e2e tests skip with different reasons depending on the runner:
"zolem and claude must both be on PATH" when the CLI is missing, but
"running nested inside an active Claude Code or Codex agent session ..."
when an agent runs the suite with the CLI present. Shared by CI
(.github/workflows/ci.yml) and the land-work project verifier
(scripts/land-work-verifier.py) so both gate on the same policy.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_NESTED_AGENT_SESSION_REASON = (
    "running nested inside an active Claude Code or Codex agent session; a "
    "spawned claude/codex CLI would inherit conflicting auth state from the "
    "outer session"
)

EXPECTED_SKIPS = {
    (
        "tests.bento_auto_allow.test_auto_allow_e2e."
        "AutoAllowHookE2ETest.test_allows_plugin_script"
    ): {"zolem and claude must both be on PATH", _NESTED_AGENT_SESSION_REASON},
    (
        "tests.bento_auto_allow.test_auto_allow_e2e."
        "AutoAllowHookE2ETest.test_blocks_outside_plugin"
    ): {"zolem and claude must both be on PATH", _NESTED_AGENT_SESSION_REASON},
    (
        "tests.bento_codex.test_codex_ws_e2e."
        "CodexBashTelemetryHookE2ETest.test_hook_records_bash_event"
    ): {
        "zolem and codex must both be on PATH for the e2e hook test",
        _NESTED_AGENT_SESSION_REASON,
    },
    (
        "tests.session_id.test_session_start_e2e."
        "SessionStartHookE2ETest.test_hook_creates_scratch_directory"
    ): {"zolem and claude must both be on PATH", _NESTED_AGENT_SESSION_REASON},
    (
        "tests.session_id.test_session_start_e2e."
        "SessionStartHookE2ETest.test_hook_writes_session_id"
    ): {"zolem and claude must both be on PATH", _NESTED_AGENT_SESSION_REASON},
    (
        "tests.session_id.test_session_start_integration."
        "SessionStartIntegrationTest.test_hook_creates_scratch_directory"
    ): {"set BENTO_INTEGRATION_TESTS=1 to run"},
    (
        "tests.session_id.test_session_start_integration."
        "SessionStartIntegrationTest.test_hook_writes_session_id_matching_claude_output"
    ): {"set BENTO_INTEGRATION_TESTS=1 to run"},
    (
        "tests.session_id.test_session_start_integration."
        "SessionStartIntegrationTest.test_session_id_stable_across_context_reset"
    ): {"set BENTO_INTEGRATION_TESTS=1 to run"},
    (
        "tests.session_id.test_session_start_integration."
        "SessionStartIntegrationTest.test_session_id_stable_across_resume"
    ): {"set BENTO_INTEGRATION_TESTS=1 to run"},
    (
        "tests.swarm.test_swarm_codex_integration."
        "SwarmCodexIntegrationTest.test_codex_exec_resume_preserves_thread_id_and_state_root"
    ): {"set RUN_CODEX_INTEGRATION=1 to run Codex CLI integration tests"},
    (
        "tests.telemetry.test_bash_telemetry_hook_e2e."
        "BashTelemetryHookE2ETest.test_hook_records_bash_event"
    ): {"zolem and claude must both be on PATH", _NESTED_AGENT_SESSION_REASON},
    (
        "tests.test_doc_claims.BeadsCodexBlockStaysMinimal.test_block_under_word_budget"
    ): {"Activate when bento-jdg minimizes the Beads block; see bento-0p1"},
    (
        "tests.test_require_worktree_hook_e2e."
        "RequireWorktreeHookE2ETest.test_allowed_on_feature_branch"
    ): {
        "zolem and claude must both be on PATH for the e2e hook test",
        _NESTED_AGENT_SESSION_REASON,
    },
    (
        "tests.test_require_worktree_hook_e2e."
        "RequireWorktreeHookE2ETest.test_allowed_with_opt_out"
    ): {
        "zolem and claude must both be on PATH for the e2e hook test",
        _NESTED_AGENT_SESSION_REASON,
    },
    (
        "tests.test_require_worktree_hook_e2e."
        "RequireWorktreeHookE2ETest.test_blocked_on_main"
    ): {
        "zolem and claude must both be on PATH for the e2e hook test",
        _NESTED_AGENT_SESSION_REASON,
    },
}


def _diff_skips(actual_skips: dict[str, str]) -> list[str]:
    """Return human-readable mismatch lines, or [] if actual matches policy."""
    problems = []
    for test_id, reason in actual_skips.items():
        if test_id not in EXPECTED_SKIPS:
            problems.append(f"unexpected skip: {test_id!r} (reason: {reason!r})")
        elif reason not in EXPECTED_SKIPS[test_id]:
            problems.append(
                f"unrecognized skip reason for {test_id!r}: {reason!r} "
                f"(acceptable: {sorted(EXPECTED_SKIPS[test_id])!r})"
            )
    for test_id in EXPECTED_SKIPS:
        if test_id not in actual_skips:
            problems.append(f"expected skip did not occur: {test_id!r}")
    return problems


def main() -> int:
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=str(REPO_ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    actual_skips = {test.id(): reason for test, reason in result.skipped}

    problems = _diff_skips(actual_skips)
    if problems:
        print("Unexpected unittest skip set.", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    if not result.wasSuccessful():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
