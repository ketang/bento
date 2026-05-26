"""End-to-end test for the require-worktree PreToolUse hook.

Drives the real ``claude`` CLI against a mock Anthropic API served by
``zolem`` (https://github.com/ketang/zolem) so we exercise the full path
Claude Code uses to dispatch hooks. This closes the gap that bento-crj
revealed: unit tests pass with a synthetic stdin payload, but cannot catch
bugs in how Claude Code constructs or passes the hook payload at runtime.

The test is skipped when ``zolem`` or ``claude`` is not on PATH, so it is
safe to ship without forcing those binaries into CI. The skip is
intentional: zolem is not yet packaged for general installation, so most
contributor and CI environments will not have it available. When zolem is
present, this test exercises the full Claude Code -> hook dispatch path
and is the only place we catch a regression where the hook executes but
fails to actually block the edit (e.g. the bento-fko ``exit 1`` bug:
unit tests asserted ``returncode != 0`` while Claude Code silently
proceeded with the tool call).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.e2e_utils import E2ETestCase, _have


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "bento"
    / "claude"
    / "scripts"
    / "require-worktree.sh"
)

BLOCKED_MESSAGE = (
    "Blocked: editing files directly on 'main' is not allowed.\n"
    "To disable this check for this repo, add 'require_worktree=false' to "
    ".agent-mode.local.\n"
)


@unittest.skipUnless(
    _have("zolem") and _have("claude"),
    "zolem and claude must both be on PATH for the e2e hook test",
)
class RequireWorktreeHookE2ETest(E2ETestCase):
    """Drive Claude Code against a zolem-mocked Anthropic API.

    Each test:
      1. starts zolem on an OS-assigned port serving the e2e-hook fixture
      2. spins up a fresh git repo wired with the require-worktree
         PreToolUse hook in ``.claude/settings.json``
      3. invokes ``claude --print`` with ``ANTHROPIC_BASE_URL`` pointed at
         zolem and a prompt that elicits the fixture's ``Write`` tool call
      4. asserts whether ``probe.txt`` was written and whether the hook's
         block message reached stderr
    """

    BACKEND = "fixture"
    FIXTURE_NS = "e2e-hook"

    def _init_repo_with_hook(self, branch: str = "main") -> Path:
        repo = self._init_repo(branch=branch)
        settings_dir = repo / ".claude"
        settings_dir.mkdir()
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Write",
                        "hooks": [
                            {"type": "command", "command": str(HOOK_SCRIPT)}
                        ],
                    }
                ]
            }
        }
        (settings_dir / "settings.json").write_text(
            json.dumps(settings, indent=2) + "\n", encoding="utf-8"
        )
        return repo

    # ----- tests ------------------------------------------------------------

    def test_blocked_on_main(self) -> None:
        repo = self._init_repo_with_hook(branch="main")

        result = self._run_claude(repo, "Please call the Write tool to create probe.txt.")

        self.assertFalse(
            (repo / "probe.txt").exists(),
            msg=f"probe.txt should not have been written on main; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        combined = result.stderr + result.stdout
        self.assertIn(
            "Blocked: editing files directly on 'main' is not allowed.",
            combined,
            msg=f"expected block message in claude output; got: {combined!r}",
        )
        self.assertZolemHit()

    def test_allowed_on_feature_branch(self) -> None:
        repo = self._init_repo_with_hook(branch="main")
        self._git(repo, "checkout", "-q", "-b", "feature-e2e")

        result = self._run_claude(repo, "Please call the Write tool to create probe.txt.")

        self.assertTrue(
            (repo / "probe.txt").exists(),
            msg=f"probe.txt should have been written on a feature branch; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertZolemHit()

    def test_allowed_with_opt_out(self) -> None:
        repo = self._init_repo_with_hook(branch="main")
        (repo / ".agent-mode.local").write_text(
            "require_worktree=false\n", encoding="utf-8"
        )

        result = self._run_claude(repo, "Please call the Write tool to create probe.txt.")

        self.assertTrue(
            (repo / "probe.txt").exists(),
            msg=f"probe.txt should have been written with opt-out; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertZolemHit()


if __name__ == "__main__":
    unittest.main()
