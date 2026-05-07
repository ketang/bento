import os
import stat
import tempfile
import unittest
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "catalog/skills/launch-work/scripts"))

import bento_extensions  # type: ignore  # noqa: E402


def _write(path: Path, content: str = "x", executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class DiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_hooks_sorted_by_numeric_prefix(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "20-second.sh", executable=True)
        _write(d / "10-first.sh", executable=True)
        _write(d / "30-third.sh", executable=True)

        result = bento_extensions.discover_directory(d, kind="hooks")

        self.assertEqual(
            [p.name for p in result.files],
            ["10-first.sh", "20-second.sh", "30-third.sh"],
        )
        self.assertEqual(result.warnings, [])

    def test_ties_break_lexicographically(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "30-bbb.sh", executable=True)
        _write(d / "30-aaa.sh", executable=True)

        result = bento_extensions.discover_directory(d, kind="hooks")
        self.assertEqual([p.name for p in result.files], ["30-aaa.sh", "30-bbb.sh"])

    def test_hidden_and_backups_silently_ignored(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "10-real.sh", executable=True)
        _write(d / ".hidden.sh", executable=True)
        _write(d / "20-edited.sh~", executable=True)
        _write(d / "30-orig.sh.bak", executable=True)

        result = bento_extensions.discover_directory(d, kind="hooks")
        self.assertEqual([p.name for p in result.files], ["10-real.sh"])
        self.assertEqual(result.warnings, [])

    def test_missing_prefix_warns_and_skips(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "10-good.sh", executable=True)
        _write(d / "no-prefix.sh", executable=True)

        result = bento_extensions.discover_directory(d, kind="hooks")
        self.assertEqual([p.name for p in result.files], ["10-good.sh"])
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("no-prefix.sh", result.warnings[0])

    def test_hooks_skip_non_executable(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "10-yes.sh", executable=True)
        _write(d / "20-no.sh", executable=False)

        result = bento_extensions.discover_directory(d, kind="hooks")
        self.assertEqual([p.name for p in result.files], ["10-yes.sh"])

    def test_actions_skip_non_md(self) -> None:
        d = self.root / "launch-work/actions/pre"
        _write(d / "10-good.md")
        _write(d / "20-not-md.txt")

        result = bento_extensions.discover_directory(d, kind="actions")
        self.assertEqual([p.name for p in result.files], ["10-good.md"])

    def test_missing_directory_returns_empty(self) -> None:
        result = bento_extensions.discover_directory(self.root / "nope", kind="hooks")
        self.assertEqual(result.files, [])
        self.assertEqual(result.warnings, [])

    def test_xdg_chain_orders_repo_first_then_user(self) -> None:
        repo = self.root / "repo"
        user = self.root / "userhome"
        os.environ["XDG_CONFIG_HOME"] = str(user / ".config")
        try:
            _write(
                repo / ".agent-plugins/bento/bento/launch-work/hooks/pre/10-repo.sh",
                executable=True,
            )
            _write(
                user / ".config/agent-plugins/bento/bento/launch-work/hooks/pre/10-user.sh",
                executable=True,
            )
            result = bento_extensions.discover(repo, "launch-work", "hooks", "pre")
            self.assertEqual(
                [p.name for p in result.files],
                ["10-repo.sh", "10-user.sh"],
            )
        finally:
            del os.environ["XDG_CONFIG_HOME"]
