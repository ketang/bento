import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check-skill-refs"


def load_module():
    loader = importlib.machinery.SourceFileLoader("check_skill_refs", str(SCRIPT))
    spec = importlib.util.spec_from_loader("check_skill_refs", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for check-skill-refs")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


mod = load_module()


class CheckSkillRefsRealTreeTest(unittest.TestCase):
    """The canonical catalog must stay clean; this is the regression guard."""

    def test_catalog_tree_has_no_unresolved_references(self) -> None:
        problems = mod.check_tree()
        self.assertEqual(problems, [], msg="\n".join(problems))


class CheckSkillRefsFixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.skills = Path(self._tmp.name) / "catalog" / "skills"
        # Two real skills so cross-skill references have somewhere to point.
        for name in ("land-work", "closure"):
            (self.skills / name / "scripts").mkdir(parents=True)
            (self.skills / name / "references").mkdir(parents=True)
        (self.skills / "closure" / "references" / "primary-branch-sync.md").write_text(
            "sync doc\n", encoding="utf-8"
        )
        (self.skills / "land-work" / "scripts" / "land-work-clean-log.py").write_text(
            "print('real')\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rel: str, text: str) -> Path:
        path = self.skills / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _check(self, rel: str) -> list[str]:
        skill_names = mod.catalog_skill_names(self.skills)
        return mod.check_markdown_file(self.skills / rel, self.skills, skill_names)

    # --- Acceptance: the three shipped defects ---------------------------------

    def test_defect_a_missing_script_reference_fails(self) -> None:
        # A reference to a script that does not exist under the skill.
        self._write(
            "land-work/SKILL.md",
            "Step 2b runs `land-work/scripts/land-work-clean-log-DELETED.py`.\n",
        )
        problems = self._check("land-work/SKILL.md")
        self.assertTrue(problems)
        self.assertIn("land-work-clean-log-DELETED.py", problems[0])

    def test_defect_a_present_script_reference_passes(self) -> None:
        self._write(
            "land-work/SKILL.md",
            "Step 2b runs `land-work/scripts/land-work-clean-log.py`.\n",
        )
        self.assertEqual(self._check("land-work/SKILL.md"), [])

    def test_defect_b_renamed_skill_line_wrapped_fails(self) -> None:
        # Old skill name wrapped across a line break inside a backtick span.
        self._write(
            "closure/SKILL.md",
            "route through `bento:issue-completeness-\nprecheck` when done.\n",
        )
        problems = self._check("closure/SKILL.md")
        self.assertTrue(problems)
        self.assertIn("issue-completeness-precheck", problems[0])

    def test_defect_b_valid_skill_line_wrapped_passes(self) -> None:
        self._write(
            "closure/SKILL.md",
            "route through `bento:land-\nwork` when done.\n",
        )
        self.assertEqual(self._check("closure/SKILL.md"), [])

    def test_defect_c_misplaced_reference_link_fails(self) -> None:
        # primary-branch-sync.md only exists under closure/, not land-work/.
        self._write(
            "land-work/references/direct-primary-branch.md",
            "See `references/primary-branch-sync.md`.\n",
        )
        problems = self._check("land-work/references/direct-primary-branch.md")
        self.assertTrue(problems)
        self.assertIn("primary-branch-sync.md", problems[0])

    def test_defect_c_cross_skill_relative_link_passes(self) -> None:
        self._write(
            "land-work/references/direct-primary-branch.md",
            "See `../../closure/references/primary-branch-sync.md`.\n",
        )
        self.assertEqual(
            self._check("land-work/references/direct-primary-branch.md"), []
        )

    # --- No false positives on out-of-catalog / placeholder tokens ------------

    def test_illustrative_and_placeholder_paths_are_ignored(self) -> None:
        self._write(
            "land-work/SKILL.md",
            "\n".join(
                [
                    "Output lines of form `path/file.py:LINE: unused`.",
                    "Write to `docs/specs/YYYY-MM-DD-plan.md`.",
                    "Template at `$XDG_CONFIG_HOME/agent-plugins/x/template.md`.",
                    "Do not assume `knowledge/INDEX.md` exists.",
                    "See https://example.com/owner/repo/blob/main/x.md for more.",
                    "Abstract `/.../skills/land-work/scripts/x.py` placeholder.",
                ]
            )
            + "\n",
        )
        self.assertEqual(self._check("land-work/SKILL.md"), [])

    def test_repo_root_relative_catalog_path_resolves(self) -> None:
        self._write(
            "land-work/references/hooks.md",
            "Runner: `catalog/skills/land-work/scripts/land-work-clean-log.py`.\n",
        )
        self.assertEqual(self._check("land-work/references/hooks.md"), [])

    def test_unknown_skill_reference_fails(self) -> None:
        self._write("closure/SKILL.md", "invoke `bento:does-not-exist` here.\n")
        problems = self._check("closure/SKILL.md")
        self.assertTrue(problems)
        self.assertIn("does-not-exist", problems[0])


if __name__ == "__main__":
    unittest.main()
