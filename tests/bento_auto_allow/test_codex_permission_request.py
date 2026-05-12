import importlib.machinery
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "bento"
    / "codex"
    / "scripts"
    / "permission-request.py"
)

PLUGIN_NAME = "bento"


def load_module():
    loader = importlib.machinery.SourceFileLoader("codex_permission_request", str(SCRIPT))
    spec = importlib.util.spec_from_loader("codex_permission_request", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CodexPermissionRequestTest(unittest.TestCase):
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

    def test_permission_request_allow_shape(self) -> None:
        decision, reason = self.module.decide(str(self.script), PLUGIN_NAME, self.root)

        self.assertIsNotNone(decision, msg=reason)
        self.assertEqual(
            decision,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {
                        "behavior": "allow",
                    },
                }
            },
        )

    def test_main_reads_codex_tool_input(self) -> None:
        stdin = io.StringIO(json.dumps({"tool_input": {"command": str(self.script)}}))
        stdout = io.StringIO()
        stderr = io.StringIO()

        self.module.main(
            argv=["permission-request.py", PLUGIN_NAME, str(self.root)],
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

        out = json.loads(stdout.getvalue())
        self.assertEqual(
            out["hookSpecificOutput"]["decision"],
            {"behavior": "allow"},
        )


class CodexSourceRepoContainmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.cache_root = Path(self.temp.name) / "cache" / "bento" / "1.0.41"
        self.cache_root.mkdir(parents=True)
        self.source_root = Path(self.temp.name) / "src"
        plugin_meta_dir = self.source_root / "plugins" / "codex" / "bento" / ".codex-plugin"
        plugin_meta_dir.mkdir(parents=True)
        (plugin_meta_dir / "plugin.json").write_text(
            '{"name":"bento","version":"0.0.0"}',
            encoding="utf-8",
        )
        scripts_dir = self.source_root / "catalog" / "skills" / "foo" / "scripts"
        scripts_dir.mkdir(parents=True)
        self.script = scripts_dir / "foo.py"
        self.script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        self.script.chmod(0o755)
        self.module = load_module()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_allows_script_in_codex_source_repo(self) -> None:
        decision, reason = self.module.decide(
            str(self.script),
            PLUGIN_NAME,
            self.cache_root,
        )

        self.assertIsNotNone(decision, msg=reason)
        self.assertIn("source repo", reason.lower())


if __name__ == "__main__":
    unittest.main()
