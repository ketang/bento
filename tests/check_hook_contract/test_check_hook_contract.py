"""Tests for scripts/check-hook-contract (the hooks-read-cwd-from-stdin lint).

See bento-k0p and the AGENTS.md rule: hook scripts must read the working
directory from the payload `cwd` field, not from `$PWD` or the process CWD.
"""

import importlib.machinery
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-hook-contract"


def _load_checker():
    loader = importlib.machinery.SourceFileLoader("check_hook_contract", str(SCRIPT))
    spec = importlib.util.spec_from_loader("check_hook_contract", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for check-hook-contract")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


checker = _load_checker()
FAKE = Path("fake/hook.py")
FAKE_SH = Path("fake/hook.sh")


def _messages(findings) -> str:
    return "\n".join(f.message for f in findings)


class RealHooksComplyTest(unittest.TestCase):
    """The lint must pass on the committed hooks (integration guard)."""

    def test_script_exits_zero_on_repo(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(REPO_ROOT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"check-hook-contract failed on committed hooks:\n{result.stderr}",
        )

    def test_finds_the_hook_scripts(self) -> None:
        scripts = checker.find_hook_scripts(REPO_ROOT)
        self.assertTrue(scripts, "expected to discover hook scripts under catalog/hooks")
        names = {p.name for p in scripts}
        self.assertIn("ensure-worktree-permissions.py", names)
        self.assertIn("require-worktree.sh", names)


class PythonCheckTest(unittest.TestCase):
    def test_flags_unannotated_getcwd(self) -> None:
        src = "import os\n\n\ndef f(payload):\n    return payload.get('cwd') or os.getcwd()\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("os.getcwd()" in m for m in _messages(findings).splitlines()))
        self.assertTrue(any("annotation" in f.message for f in findings))

    def test_flags_unannotated_path_cwd(self) -> None:
        src = "from pathlib import Path\n\n\ndef f(payload):\n    d = payload.get('cwd')\n    return d or Path.cwd()\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("Path.cwd()" in f.message for f in findings))

    def test_same_line_annotation_suppresses(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    return payload.get('cwd') or os.getcwd()  # hook-cwd-exempt: fallback\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_multiline_annotation_above_suppresses(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    cwd = payload.get('cwd')\n"
            "    if cwd is None:\n"
            "        # hook-cwd-exempt: last-resort fallback when the payload\n"
            "        # lacks a usable cwd.\n"
            "        cwd = os.getcwd()\n"
            "    return cwd\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_empty_annotation_reason_does_not_suppress(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    return payload.get('cwd') or os.getcwd()  # hook-cwd-exempt:\n"
        )
        self.assertTrue(checker.check_python_source(src, FAKE))

    def test_missing_payload_cwd_reference_is_flagged(self) -> None:
        """The historical bug: uses process CWD as the project dir, never reads
        the payload cwd. Even an annotation must not hide this."""
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    # hook-cwd-exempt: intentional\n"
            "    return os.getcwd()\n"
        )
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("never" in f.message and "cwd" in f.message for f in findings))

    def test_compliant_hook_passes(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    cwd = payload.get('cwd')\n"
            "    if cwd is None:\n"
            "        # hook-cwd-exempt: last-resort fallback only.\n"
            "        cwd = os.getcwd()\n"
            "    return cwd\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_no_primitive_no_findings(self) -> None:
        src = "import sys, json\n\n\ndef f():\n    return json.load(sys.stdin).get('tool_input')\n"
        self.assertEqual(checker.check_python_source(src, FAKE), [])


class ShellCheckTest(unittest.TestCase):
    def test_flags_unannotated_pwd(self) -> None:
        src = 'cwd="$(echo "$payload" | jq -r .cwd)"\ndir="${cwd:-$PWD}"\n'
        findings = checker.check_shell_source(src, FAKE_SH)
        self.assertTrue(any("$PWD" in f.message for f in findings))

    def test_annotation_above_suppresses_pwd(self) -> None:
        src = (
            "cwd=$(python3 -c \"import json,sys; print(json.load(sys.stdin).get('cwd') or '')\")\n"
            "# hook-cwd-exempt: last-resort default.\n"
            'dir="${cwd:-$PWD}"\n'
        )
        self.assertEqual(checker.check_shell_source(src, FAKE_SH), [])

    def test_flags_embedded_python_getcwd(self) -> None:
        src = "out=$(python3 -c \"import os; print(cwd or os.getcwd())\")\n# uses d.get('cwd')\n"
        findings = checker.check_shell_source(src, FAKE_SH)
        self.assertTrue(any("os.getcwd()" in f.message for f in findings))

    def test_missing_cwd_reference_flagged_in_shell(self) -> None:
        src = 'dir="$PWD"  # hook-cwd-exempt: deliberate\n'
        findings = checker.check_shell_source(src, FAKE_SH)
        self.assertTrue(any("never" in f.message for f in findings))

    def test_comment_only_pwd_not_flagged(self) -> None:
        src = "cwd=$(jq -r .cwd)\n# do not use $PWD here\ndir=$cwd\n"
        self.assertEqual(checker.check_shell_source(src, FAKE_SH), [])


if __name__ == "__main__":
    unittest.main()
