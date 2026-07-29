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


# Parser built via a helper that receives the parser as a parameter — the
# module-scope walker cannot attribute these arguments to any bucket.
FIXTURE_HELPER_PARAM = '''\
import argparse


def add_common(parser):
    parser.add_argument("--config", required=True)


def build_parser():
    parser = argparse.ArgumentParser(prog="demo")
    add_common(parser)
    return parser
'''

# Parser using a mutually exclusive group container.
FIXTURE_MUTEX_GROUP = '''\
import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="demo")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-file")
    group.add_argument("--from-stdin", action="store_true")
    return parser
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

    def test_optional_flags_are_still_collected(self) -> None:
        options = mod.parser_options(self.script)
        close = dict((tuple(f), req) for f, req in options["close-task"])
        self.assertEqual(close[("--branch",)], False)
        self.assertEqual(close[("--summary",)], True)


class UnsupportedPatternTest(unittest.TestCase):
    """Unmodeled parser construction must fail loudly, never silently skip."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, source: str) -> Path:
        path = self.root / "demo.py"
        path.write_text(source, encoding="utf-8")
        return path

    def test_helper_function_parameter_raises(self) -> None:
        path = self._write(FIXTURE_HELPER_PARAM)
        with self.assertRaises(mod.UnsupportedParserPatternError) as ctx:
            mod.required_option_flags(path, None)
        self.assertIn("function parameter", str(ctx.exception))

    def test_mutually_exclusive_group_raises(self) -> None:
        path = self._write(FIXTURE_MUTEX_GROUP)
        with self.assertRaises(mod.UnsupportedParserPatternError) as ctx:
            mod.required_option_flags(path, None)
        self.assertIn("add_mutually_exclusive_group", str(ctx.exception))

    def test_rebound_parameter_is_not_flagged(self) -> None:
        path = self._write(
            "import argparse\n\n\n"
            "def build(argv):\n"
            "    argv = argparse.ArgumentParser()\n"
            '    argv.add_argument("--note", required=True)\n'
            "    return argv\n"
        )
        flags = mod.required_option_flags(path, None)
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

    def test_doc_overclaiming_required_is_caught(self) -> None:
        # --branch is optional in the parser but annotated "(required)" in prose.
        command = (
            "demo/scripts/demo.py close-task --expedition <name> "
            "--outcome kept --summary <text>"
        )
        self._write_doc(command)
        with self.doc.open("a", encoding="utf-8") as fh:
            fh.write("\n- `--branch` (required) names the branch.\n")
        self._write_manifest(command)
        problems = self._check()
        self.assertTrue(
            any("--branch" in p and "(required)" in p for p in problems),
            msg="\n".join(problems),
        )

    def test_doc_annotation_matching_parser_passes(self) -> None:
        command = (
            "demo/scripts/demo.py close-task --expedition <name> "
            "--outcome kept --summary <text>"
        )
        self._write_doc(command)
        with self.doc.open("a", encoding="utf-8") as fh:
            fh.write("\n- `--summary` (required) carries the summary.\n")
        self._write_manifest(command)
        self.assertEqual(self._check(), [])

    def test_unknown_flag_annotation_is_ignored(self) -> None:
        # A flag from some other script documented in the same file.
        command = (
            "demo/scripts/demo.py close-task --expedition <name> "
            "--outcome kept --summary <text>"
        )
        self._write_doc(command)
        with self.doc.open("a", encoding="utf-8") as fh:
            fh.write("\n- `--elsewhere` (required) belongs to another tool.\n")
        self._write_manifest(command)
        self.assertEqual(self._check(), [])

    def test_unsupported_parser_pattern_surfaces_as_problem(self) -> None:
        script = self.skills / "demo" / "scripts" / "demo.py"
        script.write_text(FIXTURE_MUTEX_GROUP, encoding="utf-8")
        command = "demo/scripts/demo.py close-task"
        self._write_doc(command)
        self._write_manifest(command)
        problems = self._check()
        self.assertTrue(
            any("add_mutually_exclusive_group" in p for p in problems),
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


if __name__ == "__main__":
    unittest.main()
