import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "catalog/skills/launch-work/scripts"))

import lifecycle_extensions  # type: ignore  # noqa: E402


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

    def test_hook_scripts_sorted_by_numeric_prefix(self) -> None:
        d = self.root / "launch-work/hook-scripts/pre"
        _write(d / "20-second.sh", executable=True)
        _write(d / "10-first.sh", executable=True)
        _write(d / "30-third.sh", executable=True)

        result = lifecycle_extensions.discover_directory(d, kind="hook-scripts")

        self.assertEqual(
            [p.name for p in result.files],
            ["10-first.sh", "20-second.sh", "30-third.sh"],
        )
        self.assertEqual(result.warnings, [])

    def test_ties_break_lexicographically(self) -> None:
        d = self.root / "launch-work/hook-scripts/pre"
        _write(d / "30-bbb.sh", executable=True)
        _write(d / "30-aaa.sh", executable=True)

        result = lifecycle_extensions.discover_directory(d, kind="hook-scripts")
        self.assertEqual([p.name for p in result.files], ["30-aaa.sh", "30-bbb.sh"])

    def test_hidden_and_backups_silently_ignored(self) -> None:
        d = self.root / "launch-work/hook-scripts/pre"
        _write(d / "10-real.sh", executable=True)
        _write(d / ".hidden.sh", executable=True)
        _write(d / "20-edited.sh~", executable=True)
        _write(d / "30-orig.sh.bak", executable=True)

        result = lifecycle_extensions.discover_directory(d, kind="hook-scripts")
        self.assertEqual([p.name for p in result.files], ["10-real.sh"])
        self.assertEqual(result.warnings, [])

    def test_missing_prefix_warns_and_skips(self) -> None:
        d = self.root / "launch-work/hook-scripts/pre"
        _write(d / "10-good.sh", executable=True)
        _write(d / "no-prefix.sh", executable=True)

        result = lifecycle_extensions.discover_directory(d, kind="hook-scripts")
        self.assertEqual([p.name for p in result.files], ["10-good.sh"])
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("no-prefix.sh", result.warnings[0])

    def test_hook_scripts_skip_non_executable(self) -> None:
        d = self.root / "launch-work/hook-scripts/pre"
        _write(d / "10-yes.sh", executable=True)
        _write(d / "20-no.sh", executable=False)

        result = lifecycle_extensions.discover_directory(d, kind="hook-scripts")
        self.assertEqual([p.name for p in result.files], ["10-yes.sh"])

    def test_hook_skills_skip_non_md(self) -> None:
        d = self.root / "launch-work/hook-skills/pre"
        _write(d / "10-good.md")
        _write(d / "20-not-md.txt")

        result = lifecycle_extensions.discover_directory(d, kind="hook-skills")
        self.assertEqual([p.name for p in result.files], ["10-good.md"])

    def test_missing_directory_returns_empty(self) -> None:
        result = lifecycle_extensions.discover_directory(self.root / "nope", kind="hook-scripts")
        self.assertEqual(result.files, [])
        self.assertEqual(result.warnings, [])

    def test_xdg_chain_orders_repo_first_then_user(self) -> None:
        repo = self.root / "repo"
        user = self.root / "userhome"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(user / ".config")}):
            _write(
                repo / ".agent-plugins/bento/bento/launch-work/hook-scripts/pre/10-repo.sh",
                executable=True,
            )
            _write(
                user / ".config/agent-plugins/bento/bento/launch-work/hook-scripts/pre/10-user.sh",
                executable=True,
            )
            result = lifecycle_extensions.discover(repo, "launch-work", "hook-scripts", "pre")
            self.assertEqual(
                [p.name for p in result.files],
                ["10-repo.sh", "10-user.sh"],
            )


class VerifierDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

        # Isolate the home-scope XDG config path so tests never pick up a
        # real ~/.config/agent-plugins/bento/bento/land-work/verifier.json.
        default_xdg = self.root / "xdg-home"
        xdg_patch = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(default_xdg)})
        xdg_patch.start()
        self.addCleanup(xdg_patch.stop)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_manifest(self, root: Path, payload) -> Path:
        path = root / ".agent-plugins/bento/bento/land-work/verifier.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            import json

            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_absent_manifest_is_not_an_error(self) -> None:
        result = lifecycle_extensions.discover_verifier(self.repo)
        self.assertIsNone(result.manifest)
        self.assertIsNone(result.manifest_path)
        self.assertEqual(result.errors, [])
        # searched_paths reports where a config could be created, repo-local first
        self.assertTrue(str(result.searched_paths[0]).endswith(
            ".agent-plugins/bento/bento/land-work/verifier.json"
        ))

    def test_valid_manifest_parsed(self) -> None:
        self._write_manifest(self.repo, {
            "schema_version": 1,
            "command": ["./verify.sh", "--json"],
            "verified_noop": [{"path": "docs/gen.json", "reason": "generated"}],
        })
        result = lifecycle_extensions.discover_verifier(self.repo)
        self.assertEqual(result.errors, [])
        self.assertIsNotNone(result.manifest)
        self.assertEqual(result.manifest.command, ["./verify.sh", "--json"])
        self.assertEqual(
            result.manifest.verified_noop,
            [{"path": "docs/gen.json", "reason": "generated"}],
        )

    def test_repo_local_wins_whole_over_xdg(self) -> None:
        user = self.root / "userhome"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(user / ".config")}):
            self._write_manifest(self.repo, {
                "schema_version": 1,
                "command": ["./repo.sh"],
                "verified_noop": [],
            })
            xdg_manifest = (
                user / ".config/agent-plugins/bento/bento/land-work/verifier.json"
            )
            xdg_manifest.parent.mkdir(parents=True, exist_ok=True)
            import json

            xdg_manifest.write_text(json.dumps({
                "schema_version": 1,
                "command": ["./xdg.sh"],
                "verified_noop": [{"path": "a", "reason": "b"}],
            }), encoding="utf-8")
            result = lifecycle_extensions.discover_verifier(self.repo)
            # First existing manifest wins as a whole — no merge of exemptions.
            self.assertEqual(result.manifest.command, ["./repo.sh"])
            self.assertEqual(result.manifest.verified_noop, [])

    def test_xdg_used_when_no_repo_local(self) -> None:
        user = self.root / "userhome"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(user / ".config")}):
            xdg_manifest = (
                user / ".config/agent-plugins/bento/bento/land-work/verifier.json"
            )
            xdg_manifest.parent.mkdir(parents=True, exist_ok=True)
            import json

            xdg_manifest.write_text(json.dumps({
                "schema_version": 1,
                "command": ["./xdg.sh"],
            }), encoding="utf-8")
            result = lifecycle_extensions.discover_verifier(self.repo)
            self.assertIsNotNone(result.manifest)
            self.assertEqual(result.manifest.command, ["./xdg.sh"])

    def test_invalid_json_reports_error(self) -> None:
        self._write_manifest(self.repo, "{ not json")
        result = lifecycle_extensions.discover_verifier(self.repo)
        self.assertIsNone(result.manifest)
        self.assertTrue(any("not valid JSON" in e for e in result.errors))

    def test_wrong_schema_version_reports_error(self) -> None:
        self._write_manifest(self.repo, {"schema_version": 2, "command": ["./x"]})
        result = lifecycle_extensions.discover_verifier(self.repo)
        self.assertIsNone(result.manifest)
        self.assertTrue(any("schema_version" in e for e in result.errors))

    def test_empty_command_reports_error(self) -> None:
        self._write_manifest(self.repo, {"schema_version": 1, "command": []})
        result = lifecycle_extensions.discover_verifier(self.repo)
        self.assertIsNone(result.manifest)
        self.assertTrue(any("command" in e for e in result.errors))

    def test_verified_noop_entry_shape_validated(self) -> None:
        self._write_manifest(self.repo, {
            "schema_version": 1,
            "command": ["./x"],
            "verified_noop": [{"path": "", "reason": "r"}],
        })
        result = lifecycle_extensions.discover_verifier(self.repo)
        self.assertIsNone(result.manifest)
        self.assertTrue(any("verified_noop" in e for e in result.errors))
