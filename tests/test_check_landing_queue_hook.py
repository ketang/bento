"""Unit tests for the check-landing-queue.py Stop hook.

Full subprocess coverage (mirroring test_check_unpushed_hook.py) isn't
practical here: pending_entries() only returns non-empty when
agent_ancestor() finds a "claude"/"codex" process comm in this process's own
/proc ancestry, which a plain test-runner subprocess never has. So the
blocking path is exercised at the evaluate()/pending_entries() unit level
instead, importing each hyphenated hook script as a module.
"""

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPTS = (
    REPO_ROOT / "catalog" / "hooks" / "bento" / "claude" / "scripts" / "check-landing-queue.py",
    REPO_ROOT / "catalog" / "hooks" / "bento" / "codex" / "scripts" / "check-landing-queue.py",
)


def load_module(script: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(script))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise RuntimeError(f"unable to load {script}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CheckLandingQueueHookTest(unittest.TestCase):
    def test_blocks_when_entries_pending(self) -> None:
        for index, script in enumerate(HOOK_SCRIPTS):
            with self.subTest(script=script):
                module = load_module(script, f"check_landing_queue_{index}")
                with mock.patch.object(
                    module, "pending_entries", return_value=[{"branch": "feature-x"}]
                ):
                    reason = module.evaluate({"cwd": "/tmp"})
                self.assertIsNotNone(reason)
                self.assertIn("feature-x", reason)

    def test_cross_check_active_exempts_pending_queue(self) -> None:
        # bento-0tyd.11: without this exemption, a Stop block here would be
        # captured as the cross-check counterpart reviewer's final message
        # instead of its real review.
        for index, script in enumerate(HOOK_SCRIPTS):
            with self.subTest(script=script):
                module = load_module(script, f"check_landing_queue_cca_{index}")
                with mock.patch.object(
                    module, "pending_entries", return_value=[{"branch": "feature-x"}]
                ), mock.patch.dict(module.os.environ, {"CROSS_CHECK_ACTIVE": "1"}):
                    reason = module.evaluate({"cwd": "/tmp"})
                self.assertIsNone(reason)

    def test_cross_check_active_falsey_values_still_block(self) -> None:
        for index, script in enumerate(HOOK_SCRIPTS):
            for falsey in ("0", "false", "False", "no", ""):
                with self.subTest(script=script, falsey=falsey):
                    module = load_module(script, f"check_landing_queue_falsey_{index}_{falsey}")
                    with mock.patch.object(
                        module, "pending_entries", return_value=[{"branch": "feature-x"}]
                    ), mock.patch.dict(module.os.environ, {"CROSS_CHECK_ACTIVE": falsey}):
                        reason = module.evaluate({"cwd": "/tmp"})
                    self.assertIsNotNone(reason)

    def test_ordinary_session_without_marker_still_blocks(self) -> None:
        for index, script in enumerate(HOOK_SCRIPTS):
            with self.subTest(script=script):
                module = load_module(script, f"check_landing_queue_ordinary_{index}")
                with mock.patch.object(
                    module, "pending_entries", return_value=[{"branch": "feature-x"}]
                ), mock.patch.dict(module.os.environ, {}, clear=False):
                    module.os.environ.pop("CROSS_CHECK_ACTIVE", None)
                    reason = module.evaluate({"cwd": "/tmp"})
                self.assertIsNotNone(reason)


if __name__ == "__main__":
    unittest.main()
