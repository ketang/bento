import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_SCRIPT = REPO_ROOT / "catalog" / "skills" / "handoff" / "scripts" / "handoff.py"


class HandoffHelpTest(unittest.TestCase):
    def test_help_flag_exits_zero_and_describes_inputs(self) -> None:
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--input", result.stdout)
        self.assertIn("--slug", result.stdout)
        self.assertIn("--verbose", result.stdout)


class HandoffPreconditionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.input_path = self.tmp_path / "body.md"
        self.input_path.write_text("# body\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, cwd: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path), *extra],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_not_in_git_repo_emits_diagnostic_and_writes_no_file(self) -> None:
        non_repo = self.tmp_path / "not-a-repo"
        non_repo.mkdir()
        result = self._run(non_repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not in a git repository", result.stderr)
        self.assertEqual(list((non_repo).iterdir()), [])

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    def _make_repo_with_commit(self) -> Path:
        repo = self.tmp_path / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("hi\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def test_active_expedition_emits_diagnostic_and_writes_no_file(self) -> None:
        repo = self._make_repo_with_commit()
        # Stub expedition.py via env override so the helper sees an "active" expedition.
        fake_expedition = self.tmp_path / "fake-expedition.py"
        fake_expedition.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "if 'discover' in sys.argv:\n"
            "    cwd = os.getcwd()\n"
            "    json.dump({'ok': True, 'expeditions': [{\n"
            "        'expedition': 'demo',\n"
            "        'base_worktree': cwd,\n"
            "        'active_branches': [],\n"
            "        'current_checkout': True,\n"
            "    }]}, sys.stdout)\n"
            "    sys.stdout.write('\\n')\n",
            encoding="utf-8",
        )
        fake_expedition.chmod(0o755)
        env = os.environ.copy()
        env["BENTO_EXPEDITION_SCRIPT"] = str(fake_expedition)
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path)],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active expedition", result.stderr)
        self.assertIn("demo", result.stderr)

    def test_detached_head_emits_diagnostic_and_writes_no_file(self) -> None:
        repo = self._make_repo_with_commit()
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._git(repo, "checkout", "-q", "--detach", sha)
        existing_before = set(p.name for p in repo.iterdir())
        result = self._run(repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD is detached", result.stderr)
        existing_after = set(p.name for p in repo.iterdir())
        self.assertEqual(existing_before, existing_after)


import importlib.machinery
import importlib.util


def _load_handoff_module():
    loader = importlib.machinery.SourceFileLoader("handoff_module", str(HANDOFF_SCRIPT))
    spec = importlib.util.spec_from_loader("handoff_module", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class HandoffSuffixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.handoff = _load_handoff_module()

    def test_clean_branch_name_used_verbatim(self) -> None:
        self.assertEqual(self.handoff.sanitize_suffix("feat-foo"), "feat-foo")

    def test_branch_with_slash_replaced_with_dash(self) -> None:
        self.assertEqual(self.handoff.sanitize_suffix("user/feature"), "user-feature")

    def test_unusual_chars_replaced_with_dash(self) -> None:
        self.assertEqual(
            self.handoff.sanitize_suffix("weird name (test)#1"),
            "weird-name--test--1",
        )

    def test_only_alphanum_dot_underscore_dash_kept(self) -> None:
        self.assertEqual(
            self.handoff.sanitize_suffix("a.b_c-d"),
            "a.b_c-d",
        )

    def test_primary_branch_requires_slug(self) -> None:
        with self.assertRaises(self.handoff.HandoffError) as ctx:
            self.handoff.derive_suffix(current="main", primary="main", slug=None)
        self.assertIn("--slug", str(ctx.exception))

    def test_primary_branch_uses_slug_when_provided(self) -> None:
        self.assertEqual(
            self.handoff.derive_suffix(current="main", primary="main", slug="quick-fix"),
            "quick-fix",
        )

    def test_non_primary_branch_uses_branch_name(self) -> None:
        self.assertEqual(
            self.handoff.derive_suffix(current="user/feat", primary="main", slug=None),
            "user-feat",
        )

    def test_non_primary_branch_ignores_slug(self) -> None:
        self.assertEqual(
            self.handoff.derive_suffix(current="user/feat", primary="main", slug="ignored"),
            "user-feat",
        )


class HandoffTemplateResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.handoff = _load_handoff_module()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_repo_scope_wins_over_home_and_bundled(self) -> None:
        repo_root = self.tmp_path / "repo"
        repo_root.mkdir()
        repo_template = self._write(
            repo_root / ".agent-plugins" / "bento" / "bento" / "handoff" / "template.md",
            "REPO\n",
        )
        self._write(
            self.tmp_path / "home" / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md",
            "HOME\n",
        )
        bundled = self._write(self.tmp_path / "bundled.md", "BUNDLED\n")
        resolved = self.handoff.resolve_template(
            repo_root=repo_root,
            xdg_config_home=self.tmp_path / "home",
            bundled=bundled,
        )
        self.assertEqual(resolved, repo_template)

    def test_home_scope_wins_over_bundled_when_repo_absent(self) -> None:
        repo_root = self.tmp_path / "repo"
        repo_root.mkdir()
        home_template = self._write(
            self.tmp_path / "home" / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md",
            "HOME\n",
        )
        bundled = self._write(self.tmp_path / "bundled.md", "BUNDLED\n")
        resolved = self.handoff.resolve_template(
            repo_root=repo_root,
            xdg_config_home=self.tmp_path / "home",
            bundled=bundled,
        )
        self.assertEqual(resolved, home_template)

    def test_bundled_used_when_no_overrides(self) -> None:
        repo_root = self.tmp_path / "repo"
        repo_root.mkdir()
        bundled = self._write(self.tmp_path / "bundled.md", "BUNDLED\n")
        resolved = self.handoff.resolve_template(
            repo_root=repo_root,
            xdg_config_home=self.tmp_path / "home",
            bundled=bundled,
        )
        self.assertEqual(resolved, bundled)

    def test_xdg_default_used_when_xdg_config_home_unset(self) -> None:
        fake_home = self.tmp_path / "fake-home"
        home_template = self._write(
            fake_home / ".config" / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md",
            "HOME\n",
        )
        bundled = self._write(self.tmp_path / "bundled.md", "BUNDLED\n")
        resolved = self.handoff.resolve_template(
            repo_root=self.tmp_path / "repo-not-existing",
            xdg_config_home=None,
            bundled=bundled,
            home=fake_home,
        )
        self.assertEqual(resolved, home_template)


class HandoffSelfHealTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.handoff = _load_handoff_module()
        self.bundled = self.tmp_path / "bundled.md"
        self.bundled.write_text("BUNDLED\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_self_heal_creates_home_scope_when_missing(self) -> None:
        xdg = self.tmp_path / "xdg"
        target = xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        self.assertFalse(target.exists())
        created = self.handoff.self_heal_home_template(
            xdg_config_home=xdg, bundled=self.bundled
        )
        self.assertTrue(created)
        self.assertEqual(target.read_text(encoding="utf-8"), "BUNDLED\n")

    def test_self_heal_leaves_existing_home_scope_alone(self) -> None:
        xdg = self.tmp_path / "xdg"
        target = xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        target.parent.mkdir(parents=True)
        target.write_text("CUSTOM\n", encoding="utf-8")
        created = self.handoff.self_heal_home_template(
            xdg_config_home=xdg, bundled=self.bundled
        )
        self.assertFalse(created)
        self.assertEqual(target.read_text(encoding="utf-8"), "CUSTOM\n")

    def test_self_heal_silently_no_ops_when_bundled_missing(self) -> None:
        xdg = self.tmp_path / "xdg"
        missing_bundle = self.tmp_path / "does-not-exist.md"
        created = self.handoff.self_heal_home_template(
            xdg_config_home=xdg, bundled=missing_bundle
        )
        self.assertFalse(created)


from datetime import datetime


class HandoffPathGenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.handoff = _load_handoff_module()

    def test_path_format(self) -> None:
        moment = datetime(2026, 4, 25, 9, 5, 7)
        path = self.handoff.output_path(suffix="feat-foo", now=moment, tmp_root=Path("/tmp"))
        self.assertEqual(path, Path("/tmp/handoff-feat-foo-20260425-090507.md"))

    def test_two_consecutive_calls_with_different_seconds_yield_different_paths(self) -> None:
        a = self.handoff.output_path(
            suffix="x", now=datetime(2026, 4, 25, 9, 5, 7), tmp_root=Path("/tmp")
        )
        b = self.handoff.output_path(
            suffix="x", now=datetime(2026, 4, 25, 9, 5, 8), tmp_root=Path("/tmp")
        )
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
