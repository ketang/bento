import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog" / "hooks" / "bento" / "scripts" / "auto-allow.py"

PLUGIN_NAME = "bento"


def load_module():
    loader = importlib.machinery.SourceFileLoader("auto_allow", str(SCRIPT))
    spec = importlib.util.spec_from_loader("auto_allow", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class DecideTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "plugin"
        (self.root / "skills" / "foo" / "scripts").mkdir(parents=True)
        self.script = self.root / "skills" / "foo" / "scripts" / "foo.py"
        self.script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        self.script.chmod(0o755)
        self.module = load_module()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _decide(self, command: str):
        return self.module.decide(command, PLUGIN_NAME, self.root)

    def test_allows_plugin_script(self) -> None:
        decision, _ = self._decide(f"{self.script} --flag")
        self.assertIsNotNone(decision)
        self.assertEqual(
            decision["hookSpecificOutput"]["permissionDecision"], "allow"
        )
        self.assertIn(PLUGIN_NAME, decision["hookSpecificOutput"]["permissionDecisionReason"])

    def test_allow_output_shape(self) -> None:
        decision, _ = self._decide(str(self.script))
        self.assertEqual(
            decision["hookSpecificOutput"]["hookEventName"], "PreToolUse"
        )

    def test_refuses_when_path_outside_plugin_root(self) -> None:
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        outside.chmod(0o755)
        decision, reason = self._decide(str(outside))
        self.assertIsNone(decision)
        self.assertIn("outside", reason.lower())

    def test_refuses_compound_and(self) -> None:
        decision, reason = self._decide(f"{self.script} && rm -rf /")
        self.assertIsNone(decision)
        self.assertIn("compound", reason.lower())

    def test_refuses_compound_or(self) -> None:
        decision, _ = self._decide(f"{self.script} || true")
        self.assertIsNone(decision)

    def test_refuses_semicolon(self) -> None:
        decision, _ = self._decide(f"{self.script} ; echo done")
        self.assertIsNone(decision)

    def test_refuses_pipe(self) -> None:
        decision, _ = self._decide(f"{self.script} | cat")
        self.assertIsNone(decision)

    def test_refuses_redirect_out(self) -> None:
        decision, _ = self._decide(f"{self.script} > /tmp/out")
        self.assertIsNone(decision)

    def test_refuses_redirect_in(self) -> None:
        decision, _ = self._decide(f"{self.script} < /tmp/in")
        self.assertIsNone(decision)

    def test_refuses_command_substitution(self) -> None:
        decision, _ = self._decide(f"{self.script} --flag=$(whoami)")
        self.assertIsNone(decision)

    def test_refuses_backticks(self) -> None:
        decision, _ = self._decide(f"{self.script} --flag=`whoami`")
        self.assertIsNone(decision)

    def test_refuses_newline(self) -> None:
        decision, _ = self._decide(f"{self.script}\nrm -rf /")
        self.assertIsNone(decision)

    def test_refuses_when_file_missing(self) -> None:
        missing = self.root / "skills" / "foo" / "scripts" / "missing.py"
        decision, reason = self._decide(str(missing))
        self.assertIsNone(decision)
        self.assertIn("not found", reason.lower())

    def test_refuses_when_not_py(self) -> None:
        sh = self.root / "skills" / "foo" / "scripts" / "foo.sh"
        sh.write_text("#!/bin/sh\n", encoding="utf-8")
        sh.chmod(0o755)
        decision, reason = self._decide(str(sh))
        self.assertIsNone(decision)
        self.assertIn(".py", reason)

    def test_refuses_when_symlink_escapes_root(self) -> None:
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        outside.chmod(0o755)
        link = self.root / "skills" / "foo" / "scripts" / "link.py"
        os.symlink(outside, link)
        decision, reason = self._decide(str(link))
        self.assertIsNone(decision)
        self.assertIn("outside", reason.lower())

    def test_refuses_when_directory(self) -> None:
        d = self.root / "skills" / "foo" / "scripts" / "pkg.py"
        d.mkdir()
        decision, reason = self._decide(str(d))
        self.assertIsNone(decision)
        self.assertIn("regular file", reason.lower())

    def test_refuses_empty_command(self) -> None:
        decision, _ = self._decide("")
        self.assertIsNone(decision)

    def test_refuses_unterminated_quotes(self) -> None:
        decision, reason = self._decide(f"'{self.script}")
        self.assertIsNone(decision)
        self.assertIn("parse", reason.lower())

    def test_refuses_when_first_token_is_python_interpreter(self) -> None:
        decision, _ = self._decide(f"python3 {self.script}")
        self.assertIsNone(decision)


class RunMainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "plugin"
        (self.root / "scripts").mkdir(parents=True)
        self.script = self.root / "scripts" / "tool.py"
        self.script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        self.script.chmod(0o755)
        self.module = load_module()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_main_allow(self) -> None:
        import io, json
        stdin = io.StringIO(json.dumps({"tool_input": {"command": str(self.script)}}))
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.module.main(
            argv=["auto-allow.py", PLUGIN_NAME, str(self.root)],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
        out = json.loads(stdout.getvalue())
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_main_noop_outside_root(self) -> None:
        import io, json
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        outside.chmod(0o755)
        stdin = io.StringIO(json.dumps({"tool_input": {"command": str(outside)}}))
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.module.main(
            argv=["auto-allow.py", PLUGIN_NAME, str(self.root)],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("outside", stderr.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
