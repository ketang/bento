import importlib.machinery
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_PATH = REPO_ROOT / "catalog" / "hooks" / "telemetry" / "scripts" / "bento_telemetry.py"


def load_lib():
    loader = importlib.machinery.SourceFileLoader("bento_telemetry", str(LIB_PATH))
    spec = importlib.util.spec_from_loader("bento_telemetry", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ClassifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = load_lib()

    def test_zero_exit_is_ok_when_not_interrupted(self) -> None:
        self.assertEqual(self.lib.classify(0, "", False), "ok")

    def test_interrupted_zero_exit_is_error(self) -> None:
        self.assertEqual(self.lib.classify(0, "", True), "error")

    def test_127_with_no_such_file_is_not_found(self) -> None:
        self.assertEqual(
            self.lib.classify(127, "bash: /x/foo.py: No such file or directory", False),
            "not_found",
        )

    def test_126_with_permission_denied_is_not_found(self) -> None:
        self.assertEqual(
            self.lib.classify(126, "bash: /x/foo.py: Permission denied", False),
            "not_found",
        )

    def test_127_without_recognized_stderr_is_error(self) -> None:
        self.assertEqual(self.lib.classify(127, "weird stderr", False), "error")

    def test_nonzero_runtime_exit_is_error(self) -> None:
        self.assertEqual(self.lib.classify(1, "Traceback ...", False), "error")


class RedactStderrTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = load_lib()

    def test_empty_returns_empty_list(self) -> None:
        self.assertEqual(self.lib.redact_stderr(""), [])

    def test_home_prefix_is_replaced(self) -> None:
        out = self.lib.redact_stderr("error at /home/user/project/file.py", home="/home/user")
        self.assertEqual(out, ["error at ~/project/file.py"])

    def test_session_scratch_path_is_replaced(self) -> None:
        out = self.lib.redact_stderr(
            "wrote /tmp/claude-session-abc123/log.txt",
            home="/nonexistent",
        )
        self.assertEqual(out, ["wrote <scratch>/log.txt"])

    def test_tail_is_limited_to_twenty_lines(self) -> None:
        text = "\n".join(f"line-{i}" for i in range(30))
        out = self.lib.redact_stderr(text, home="/nonexistent")
        self.assertEqual(len(out), 20)
        self.assertEqual(out[0], "line-10")
        self.assertEqual(out[-1], "line-29")

    def test_tail_is_limited_to_four_kibibytes(self) -> None:
        text = "x" * 5000
        out = self.lib.redact_stderr(text, home="/nonexistent")
        self.assertEqual(len("\n".join(out).encode("utf-8")), 4096)


class AttributeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = load_lib()

    def test_realistic_cache_layout_matches(self) -> None:
        out = self.lib.attribute(
            "/home/u/.codex/plugins/cache/bento/bento/36905842/skills/land-work/scripts/land-work-prepare.py"
        )
        self.assertEqual(
            out,
            {
                "marketplace": "bento",
                "plugin": "bento",
                "skill": "land-work",
                "script": "land-work-prepare.py",
            },
        )

    def test_dev_layout_matches(self) -> None:
        out = self.lib.attribute(
            "/home/u/project/bento/catalog/skills/swarm/scripts/swarm-triage.py"
        )
        self.assertEqual(
            out,
            {
                "marketplace": "bento",
                "plugin": "(dev)",
                "skill": "swarm",
                "script": "swarm-triage.py",
            },
        )

    def test_unrelated_path_returns_none(self) -> None:
        self.assertIsNone(self.lib.attribute("/usr/bin/ls"))
        self.assertIsNone(self.lib.attribute("/home/u/some/other/script.py"))


class StoreAndAppendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = load_lib()
        self.temp = tempfile.TemporaryDirectory()
        self.orig_xdg = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.temp.name

    def tearDown(self) -> None:
        if self.orig_xdg is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.orig_xdg
        self.temp.cleanup()

    def test_store_dir_uses_xdg_state_home_and_is_not_world_accessible(self) -> None:
        path = self.lib.store_dir()
        self.assertEqual(path, Path(self.temp.name) / "bento" / "telemetry")
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode & 0o007, 0)

    def test_append_record_writes_jsonl_file_that_is_not_world_accessible(self) -> None:
        now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
        path = self.lib.append_record({"v": 1, "kind": "test", "id": "a"}, now=now)
        self.lib.append_record({"v": 1, "kind": "test", "id": "b"}, now=now)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["id"] for line in lines], ["a", "b"])
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode & 0o007, 0)


class MakeScriptRecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = load_lib()

    def test_unwatched_path_returns_none(self) -> None:
        rec = self.lib.make_script_record(
            argv=["/usr/bin/ls", "-la"],
            exit_code=0,
            stderr="",
            interrupted=False,
            duration_ms=10,
            realpath="/usr/bin/ls",
            session_id="s1",
        )
        self.assertIsNone(rec)

    def test_watched_runtime_error_record_shape(self) -> None:
        rec = self.lib.make_script_record(
            argv=[
                "/x/cache/bento/bento/36905842/skills/land-work/scripts/land-work-prepare.py",
                "--apply",
                "--base",
                "main",
            ],
            exit_code=1,
            stderr="/home/user/project\nTraceback ...\nValueError: bad",
            interrupted=False,
            duration_ms=42,
            realpath="/x/cache/bento/bento/36905842/skills/land-work/scripts/land-work-prepare.py",
            session_id="s1",
            home="/home/user",
            now=datetime(2026, 4, 26, 17, 13, 42, 812000, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec["v"], 1)
        self.assertEqual(rec["kind"], "script")
        self.assertEqual(rec["session_id"], "s1")
        self.assertEqual(rec["marketplace"], "bento")
        self.assertEqual(rec["plugin"], "bento")
        self.assertEqual(rec["skill"], "land-work")
        self.assertEqual(rec["script"], "land-work-prepare.py")
        self.assertEqual(rec["argv_redacted"], ["--apply", "--base", "main"])
        self.assertEqual(rec["exit"], 1)
        self.assertEqual(rec["class"], "error")
        self.assertFalse(rec["interrupted"])
        self.assertEqual(rec["duration_ms"], 42)
        self.assertEqual(rec["ts"], "2026-04-26T17:13:42.812Z")
        self.assertEqual(rec["stderr_tail"][0], "~/project")

    def test_interrupted_record_is_error(self) -> None:
        rec = self.lib.make_script_record(
            argv=["/x/cache/bento/bento/v/skills/swarm/scripts/swarm-triage.py"],
            exit_code=0,
            stderr="",
            interrupted=True,
            duration_ms=5,
            realpath="/x/cache/bento/bento/v/skills/swarm/scripts/swarm-triage.py",
            session_id="s1",
        )
        self.assertEqual(rec["class"], "error")
        self.assertTrue(rec["interrupted"])


if __name__ == "__main__":
    unittest.main()
