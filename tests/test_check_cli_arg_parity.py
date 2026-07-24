import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check-cli-arg-parity"


def load_module():
    loader = importlib.machinery.SourceFileLoader("check_cli_arg_parity", str(SCRIPT))
    spec = importlib.util.spec_from_loader("check_cli_arg_parity", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for check-cli-arg-parity")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


mod = load_module()


# An expedition-shaped mini CLI: a subcommand whose parser marks --summary
# required, reproducing the exact defect this check exists to catch.
FIXTURE_SCRIPT = '''\
import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="demo")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("close-task")
    p.add_argument("--expedition", required=True)
    p.add_argument("--outcome", choices=("kept", "failed"), required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--branch")

    p = sub.add_parser("verify")
    p.add_argument("--expedition", required=True)

    return parser


if __name__ == "__main__":
    build_parser().parse_args()
'''

# A single-command CLI whose parser (built inline in main, not build_parser)
# marks --note required.
FIXTURE_SINGLE = '''\
import argparse


def main():
    parser = argparse.ArgumentParser(prog="report")
    parser.add_argument("--note", required=True)
    parser.add_argument("--target")
    return parser.parse_args()
'''


class RealCorpusTest(unittest.TestCase):
    """The canonical catalog must stay clean; this is the regression guard."""

    def test_catalog_manifests_pass(self) -> None:
        problems = mod.check_tree()
        self.assertEqual(problems, [], msg="\n".join(problems))


class IntrospectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.script = self.root / "demo.py"
        self.script.write_text(FIXTURE_SCRIPT, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_subcommand_required_flags(self) -> None:
        flags = mod.required_option_flags(self.script, "close-task")
        self.assertEqual(
            sorted(f[0] for f in flags),
            ["--expedition", "--outcome", "--summary"],
        )

    def test_other_subcommand_isolated(self) -> None:
        flags = mod.required_option_flags(self.script, "verify")
        self.assertEqual([f[0] for f in flags], ["--expedition"])

    def test_optional_flag_not_reported(self) -> None:
        flags = mod.required_option_flags(self.script, "close-task")
        self.assertNotIn("--branch", [f[0] for f in flags])

    def test_single_command_parser_built_in_main(self) -> None:
        single = self.root / "report.py"
        single.write_text(FIXTURE_SINGLE, encoding="utf-8")
        flags = mod.required_option_flags(single, None)
        self.assertEqual([f[0] for f in flags], ["--note"])


class ManifestFixtureTest(unittest.TestCase):
    """End-to-end: manifest + doc + script laid out like a real skill."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.skills = base / "catalog" / "skills"
        skill = self.skills / "demo"
        (skill / "scripts").mkdir(parents=True)
        (skill / "scripts" / "demo.py").write_text(FIXTURE_SCRIPT, encoding="utf-8")
        self.doc = skill / "SKILL.md"
        self.manifests = base / "cli-parity"
        self.manifests.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_doc(self, command: str) -> None:
        self.doc.write_text(
            f"# Demo\n\nRun the closer:\n\n    {command}\n", encoding="utf-8"
        )

    def _write_manifest(self, command: str) -> None:
        (self.manifests / "demo.json").write_text(
            json.dumps(
                {
                    "invocations": [
                        {
                            "doc": "SKILL.md",
                            "command": command,
                            "script": "scripts/demo.py",
                            "subcommand": "close-task",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def _check(self):
        return mod.check_tree(self.manifests, self.skills)

    def test_regression_missing_summary_is_caught(self) -> None:
        # Reproduces the expedition defect: documented close-task omits the
        # parser-required --summary flag.
        command = "demo/scripts/demo.py close-task --expedition <name> --outcome kept"
        self._write_doc(command)
        self._write_manifest(command)
        problems = self._check()
        self.assertTrue(problems, "expected a parity failure")
        self.assertTrue(
            any("--summary" in p for p in problems),
            msg="\n".join(problems),
        )

    def test_complete_command_passes(self) -> None:
        command = (
            "demo/scripts/demo.py close-task --expedition <name> "
            "--outcome kept --summary <text>"
        )
        self._write_doc(command)
        self._write_manifest(command)
        self.assertEqual(self._check(), [])

    def test_manifest_drift_from_prose_is_caught(self) -> None:
        # Command satisfies parity but no longer appears in the doc.
        full = (
            "demo/scripts/demo.py close-task --expedition <name> "
            "--outcome kept --summary <text>"
        )
        self._write_doc("demo/scripts/demo.py verify --expedition <name>")
        self._write_manifest(full)
        problems = self._check()
        self.assertTrue(
            any("not found in SKILL.md" in p for p in problems),
            msg="\n".join(problems),
        )

    def test_multiline_command_normalizes(self) -> None:
        # Documented as a wrapped, backslash-continued block; manifest stores
        # the single-line form.
        self.doc.write_text(
            "# Demo\n\n```bash\n"
            "demo/scripts/demo.py close-task \\\n"
            "  --expedition <name> \\\n"
            "  --outcome kept \\\n"
            "  --summary <text>\n"
            "```\n",
            encoding="utf-8",
        )
        self._write_manifest(
            "demo/scripts/demo.py close-task --expedition <name> "
            "--outcome kept --summary <text>"
        )
        self.assertEqual(self._check(), [])


class RequiredFlagBucketsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.script = Path(self._tmp.name) / "demo.py"
        self.script.write_text(FIXTURE_SCRIPT, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_buckets_group_every_subcommand(self) -> None:
        buckets = mod.required_flag_buckets(self.script)
        self.assertEqual(
            {k: sorted(f[0] for f in v) for k, v in buckets.items()},
            {
                "close-task": ["--expedition", "--outcome", "--summary"],
                "verify": ["--expedition"],
            },
        )

    def test_buckets_omit_flagless_subcommands(self) -> None:
        # No top-level (None) required flags in the fixture => no None bucket.
        self.assertNotIn(None, mod.required_flag_buckets(self.script))


class CoverageTest(unittest.TestCase):
    """The coverage gate: documented required-flag CLIs must have a manifest."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.skills = base / "catalog" / "skills"
        self.skill = self.skills / "demo"
        (self.skill / "scripts").mkdir(parents=True)
        (self.skill / "scripts" / "demo.py").write_text(FIXTURE_SCRIPT, encoding="utf-8")
        self.doc = self.skill / "SKILL.md"
        self.manifests = base / "cli-parity"
        self.manifests.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_manifest(self, subcommands) -> None:
        (self.manifests / "demo.json").write_text(
            json.dumps(
                {
                    "invocations": [
                        {
                            "doc": "SKILL.md",
                            "command": f"demo/scripts/demo.py {sub}",
                            "script": "scripts/demo.py",
                            "subcommand": sub,
                        }
                        for sub in subcommands
                    ]
                }
            ),
            encoding="utf-8",
        )

    def _coverage(self):
        return mod.check_coverage(self.manifests, self.skills)

    def test_documented_uncovered_subcommand_is_flagged(self) -> None:
        # close-task is documented but no manifest exists at all.
        self.doc.write_text(
            "# Demo\n\n    demo/scripts/demo.py close-task --expedition x "
            "--outcome kept --summary y\n",
            encoding="utf-8",
        )
        problems = self._coverage()
        self.assertTrue(
            any("close-task" in p and "no scripts/cli-parity" in p for p in problems),
            msg="\n".join(problems),
        )

    def test_covered_subcommand_passes(self) -> None:
        self.doc.write_text(
            "# Demo\n\n    demo/scripts/demo.py close-task --expedition x "
            "--outcome kept --summary y\n",
            encoding="utf-8",
        )
        self._write_manifest(["close-task"])
        self.assertEqual(self._coverage(), [])

    def test_undocumented_subcommand_is_not_flagged(self) -> None:
        # verify carries a required flag but nothing documents it -> no risk.
        self.doc.write_text(
            "# Demo\n\n    demo/scripts/demo.py close-task --expedition x "
            "--outcome kept --summary y\n",
            encoding="utf-8",
        )
        self._write_manifest(["close-task"])
        self.assertEqual(self._coverage(), [])

    def test_partial_coverage_flags_only_the_gap(self) -> None:
        # Both subcommands documented; only close-task has a manifest entry.
        self.doc.write_text(
            "# Demo\n\n"
            "    demo/scripts/demo.py close-task --expedition x --outcome kept --summary y\n"
            "    demo/scripts/demo.py verify --expedition x\n",
            encoding="utf-8",
        )
        self._write_manifest(["close-task"])
        problems = self._coverage()
        self.assertTrue(any("verify" in p for p in problems), msg="\n".join(problems))
        self.assertFalse(any("close-task" in p for p in problems), msg="\n".join(problems))

    def test_documented_in_reference_file_counts(self) -> None:
        # Invocation lives in references/*.md, not SKILL.md.
        (self.skill / "references").mkdir()
        (self.skill / "references" / "usage.md").write_text(
            "    demo/scripts/demo.py close-task --expedition x --outcome kept --summary y\n",
            encoding="utf-8",
        )
        self.doc.write_text("# Demo\n", encoding="utf-8")
        problems = self._coverage()
        self.assertTrue(any("close-task" in p for p in problems), msg="\n".join(problems))


if __name__ == "__main__":
    unittest.main()
