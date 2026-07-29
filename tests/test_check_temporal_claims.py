"""Tests for scripts/check-temporal-claims (bento-5zg)."""

import contextlib
import importlib.machinery
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check-temporal-claims"

# The exact bentobug SKILL.md step 5 prose as it shipped before 6752009 fixed
# it. It promised persistence "in a follow-up" for weeks after the report
# writer had already landed. This is the regression fixture: the linter must
# fail on it.
BENTOBUG_PRE_FIX_STEP5 = """\
4. Show the user the assembled block verbatim so they can confirm it before
   any persistence step ships.
5. Tell the user persistence ships in a follow-up (the report writer); for
   now the captured block is the artifact.
"""


def load_module():
    loader = importlib.machinery.SourceFileLoader("check_temporal_claims", str(SCRIPT))
    spec = importlib.util.spec_from_loader("check_temporal_claims", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for check-temporal-claims")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CheckTemporalClaimsRealTreeTest(unittest.TestCase):
    def test_catalog_tree_has_no_unanchored_temporal_claims(self) -> None:
        problems = load_module().check_tree()
        self.assertEqual(problems, [], "unanchored temporal claims:\n" + "\n".join(problems))


class BentobugRegressionTest(unittest.TestCase):
    """Acceptance criterion: the pre-fix bentobug step 5 text must fail."""

    def setUp(self) -> None:
        self.mod = load_module()

    def test_pre_fix_step5_is_flagged(self) -> None:
        problems = self.mod.check_text(BENTOBUG_PRE_FIX_STEP5, label="bentobug/SKILL.md")
        joined = "\n".join(problems)
        self.assertTrue(problems, "pre-fix bentobug step 5 text was not flagged")
        self.assertIn("follow-up", joined)
        self.assertIn("for now", joined)

    def test_pre_fix_step5_passes_when_anchored_with_tracker_id(self) -> None:
        anchored = BENTOBUG_PRE_FIX_STEP5.replace(
            "(the report writer)", "(the report writer, bento-fmx.3)"
        ).replace("for\n   now", "for now (bento-fmx.3)")
        self.assertEqual(self.mod.check_text(anchored), [])

    def test_shipped_replacement_text_passes(self) -> None:
        shipped = (
            "5. After the user confirms the block, persist it by invoking the "
            "report writer.\n"
        )
        self.assertEqual(self.mod.check_text(shipped), [])


class ClaimShapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()

    def _check(self, text: str) -> list[str]:
        return self.mod.check_text(text, label="f.md")

    def test_flagged_shapes(self) -> None:
        for text in (
            "For now the block is the artifact.",
            "Telemetry enrichment is coming soon.",
            "Persistence lands as a follow-up.",
            "A follow-up will add the writer.",
            "The Codex path is not yet implemented.",
            "Codex support is not yet available.",
            "A `--json` flag will be added later.",
        ):
            with self.subTest(text=text):
                self.assertTrue(self._check(text), f"not flagged: {text!r}")

    def test_benign_corpus_shapes_are_not_flagged(self) -> None:
        # Real lines from catalog/skills that use the bare words in a
        # non-claim sense. Flagging these would make the linter noise.
        for text in (
            "- Create tracker follow-up items for Minor issues that are real.",
            "Summarize what landed, what was deferred, and any follow-up risks.",
            "Keep follow-up actions concrete and specific.",
            "| `checked_out_in_worktree` | Not yet merged; needs investigation |",
            "What was run, what passed, what failed, what was not yet tested.",
            "If actionable children exist but are not yet marked ready, report it.",
            "...is not yet published — refuse to close until the branch is pushed.",
            "a skill not yet published to the installed plugin cache",
        ):
            with self.subTest(text=text):
                self.assertEqual(self._check(text), [], f"false positive: {text!r}")


class AnchorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()

    def test_tracker_id_on_same_line_anchors(self) -> None:
        self.assertEqual(
            self.mod.check_text("For now the block is the artifact (bento-5zg)."), []
        )

    def test_dotted_sub_id_anchors(self) -> None:
        self.assertEqual(
            self.mod.check_text("Codex support is not yet implemented; see bento-96ua.2."),
            [],
        )

    def test_tracker_id_on_preceding_line_anchors(self) -> None:
        text = "<!-- tracked by bento-5zg -->\nFor now the block is the artifact.\n"
        self.assertEqual(self.mod.check_text(text), [])

    def test_blank_lines_between_annotation_and_claim_are_skipped(self) -> None:
        text = "<!-- tracked by bento-5zg -->\n\n\nFor now the block is the artifact.\n"
        self.assertEqual(self.mod.check_text(text), [])

    def test_tracker_id_two_lines_above_does_not_anchor(self) -> None:
        text = (
            "<!-- tracked by bento-5zg -->\n"
            "Some unrelated prose sentence.\n"
            "For now the block is the artifact.\n"
        )
        self.assertTrue(self.mod.check_text(text))

    def test_suppression_marker_with_reason_anchors(self) -> None:
        text = (
            'Tell the user "for now" verbatim. '
            "<!-- temporal-claim-ok: example text the agent emits -->\n"
        )
        self.assertEqual(self.mod.check_text(text), [])

    def test_suppression_marker_without_reason_does_not_anchor(self) -> None:
        text = 'Tell the user "for now" verbatim. <!-- temporal-claim-ok: -->\n'
        self.assertTrue(self.mod.check_text(text))

    def test_other_tracker_prefix_is_configurable(self) -> None:
        text = "For now the block is the artifact (acme-123).\n"
        self.assertTrue(self.mod.check_text(text))
        self.assertEqual(self.mod.check_text(text, issue_prefix="acme"), [])


class OutputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()

    def test_problem_names_file_and_line(self) -> None:
        text = "intro\n\nFor now the block is the artifact.\n"
        problems = self.mod.check_text(text, label="catalog/skills/x/SKILL.md")
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("catalog/skills/x/SKILL.md:3:"))

    def _run_main(self, body: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills" / "demo"
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text(body, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                return self.mod.main(["--skills-root", str(Path(tmp) / "skills")])

    def test_main_exits_nonzero_on_violation(self) -> None:
        self.assertEqual(self._run_main("For now nothing works.\n"), 1)

    def test_main_exits_zero_on_clean_tree(self) -> None:
        self.assertEqual(self._run_main("All shipped.\n"), 0)


if __name__ == "__main__":
    unittest.main()
