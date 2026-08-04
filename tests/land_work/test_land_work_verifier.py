import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.script_test_utils import git, run


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_SCRIPT = REPO_ROOT / "catalog/skills/land-work/scripts/land-work-run-verifier.py"


PASS_EMPTY_VERIFIER = (
    '#!/usr/bin/env bash\n'
    'echo \'{"schema_version":1,"status":"passed","selected_checks":[]}\'\n'
)
PASS_ONE_CHECK_VERIFIER = (
    '#!/usr/bin/env bash\n'
    'echo \'{"schema_version":1,"status":"passed",'
    '"selected_checks":[{"name":"make test-quick","status":"passed"}]}\'\n'
)
FAILED_CHECK_VERIFIER = (
    '#!/usr/bin/env bash\n'
    'echo \'{"schema_version":1,"status":"passed",'
    '"selected_checks":[{"name":"make test-quick","status":"failed"}]}\'\n'
)
FAILED_STATUS_VERIFIER = (
    '#!/usr/bin/env bash\n'
    'echo \'{"schema_version":1,"status":"failed","selected_checks":[]}\'\n'
)
INVALID_JSON_VERIFIER = '#!/usr/bin/env bash\necho not-json\n'
NONZERO_VERIFIER = '#!/usr/bin/env bash\necho boom >&2\nexit 3\n'
SLOW_VERIFIER = '#!/usr/bin/env bash\nsleep 5\necho ok\n'


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class LandWorkVerifierTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.repo = base / "repo"
        self.worktree = base / "feature-worktree"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Verifier Test")
        git(self.repo, "config", "user.email", "verifier@example.com")
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial commit")
        self.base_sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()

        git(self.repo, "worktree", "add", "-b", "feature/noop", str(self.worktree), "main")
        (self.worktree / "src").mkdir()
        (self.worktree / "src" / "feature.go").write_text("package main\n", encoding="utf-8")
        git(self.worktree, "add", "src/feature.go")
        git(self.worktree, "commit", "-m", "add feature")
        self.head_sha = git(self.worktree, "rev-parse", "HEAD").stdout.strip()

        # Isolate the home-scope XDG config path so tests never pick up a
        # real ~/.config/agent-plugins/bento/bento/land-work/verifier.json.
        default_xdg = base / "xdg-home"
        xdg_patch = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(default_xdg)})
        xdg_patch.start()
        self.addCleanup(xdg_patch.stop)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -- helpers ---------------------------------------------------------- #

    @property
    def verifier_path(self) -> Path:
        # Placed outside the repo so it never enters the candidate diff union.
        return Path(self.temp_dir.name) / "verify.sh"

    def write_manifest(self, verified_noop=None, *, root: Path | None = None, command=None) -> None:
        root = root or self.repo
        manifest = {
            "schema_version": 1,
            "command": command or [str(self.verifier_path)],
            "verified_noop": verified_noop or [],
        }
        path = root / ".agent-plugins/bento/bento/land-work/verifier.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def install_verifier(self, content: str) -> None:
        _write_executable(self.verifier_path, content)

    def run_verifier(self, *extra: str, candidate: Path | None = None, timeout: str | None = None,
                     check: bool = False) -> subprocess.CompletedProcess[str]:
        candidate = candidate or self.worktree
        args = [
            str(VERIFIER_SCRIPT),
            "--repo-root", str(self.repo),
            "--candidate", str(candidate),
            "--base-sha", self.base_sha,
            "--head-sha", self.head_sha,
        ]
        if timeout is not None:
            args += ["--timeout", timeout]
        args += list(extra)
        return run(args, self.repo, check=check)

    # -- reproduction: no-op verifier on a real diff ---------------------- #

    def test_noop_verifier_on_real_diff_fails_closed(self) -> None:
        self.write_manifest()
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])

        result = self.run_verifier()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["base_sha"], self.base_sha)
        self.assertEqual(payload["head_sha"], self.head_sha)
        self.assertEqual(payload["candidate"], str(self.worktree.resolve()))
        self.assertIn("src/feature.go", payload["changed_paths"]["committed"])
        self.assertEqual(payload["exemptions"], [])
        self.assertEqual(payload["verifier_command"], [str(self.verifier_path)])
        self.assertEqual(payload["selected_check_count"], 0)
        self.assertEqual(payload["unverified_paths"], ["src/feature.go"])
        # diagnostics must not leak file contents
        self.assertNotIn("package main", result.stdout)

    def test_exact_exemption_makes_noop_pass(self) -> None:
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "src/feature.go", "reason": "generated identity"}],
        )
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["exemptions"], ["src/feature.go"])
        self.assertEqual(payload["relevant_paths"], [])

    def test_glob_exemption_rejected(self) -> None:
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "src/*.go", "reason": "glob"}],
        )
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("glob" in e for e in payload["errors"]))

    def test_directory_exemption_rejected(self) -> None:
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "src/", "reason": "dir"}],
        )
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("directory" in e for e in payload["errors"]))

    def test_absolute_exemption_rejected(self) -> None:
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "/etc/passwd", "reason": "abs"}],
        )
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("absolute" in e for e in payload["errors"]))

    def test_dotdot_exemption_rejected(self) -> None:
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "src/../src/feature.go", "reason": ".."}],
        )
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any(".." in e for e in payload["errors"]))

    def test_near_match_exemption_does_not_exempt(self) -> None:
        # An exemption for a sibling path does not exempt src/feature.go.
        (self.worktree / "src" / "feature.go.bak").write_text("x\n", encoding="utf-8")
        git(self.worktree, "add", "src/feature.go.bak")
        git(self.worktree, "commit", "-m", "add bak")
        self.head_sha = git(self.worktree, "rev-parse", "HEAD").stdout.strip()
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "src/feature.go.bak", "reason": "near"}],
        )
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["unverified_paths"], ["src/feature.go"])

    def test_stale_exemption_path_rejected(self) -> None:
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "does/not/exist.txt", "reason": "stale"}],
        )
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("does not exist" in e for e in payload["errors"]))

    # -- manifest precedence --------------------------------------------- #

    def test_repo_local_manifest_overrides_xdg(self) -> None:
        home = Path(self.temp_dir.name) / "home"
        xdg = home / ".config"
        # Lower-precedence (XDG) manifest exempts the path; repo-local does not.
        xdg_manifest = xdg / "agent-plugins/bento/bento/land-work/verifier.json"
        xdg_manifest.parent.mkdir(parents=True, exist_ok=True)
        xdg_manifest.write_text(json.dumps({
            "schema_version": 1,
            "command": [str(self.verifier_path)],
            "verified_noop": [{"path": "src/feature.go", "reason": "xdg"}],
        }), encoding="utf-8")
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])  # repo-local, no exemptions

        env_extra = {"XDG_CONFIG_HOME": str(xdg)}
        args = [
            str(VERIFIER_SCRIPT),
            "--repo-root", str(self.repo),
            "--candidate", str(self.worktree),
            "--base-sha", self.base_sha,
            "--head-sha", self.head_sha,
        ]
        proc = subprocess.run(args, cwd=self.repo, check=False, capture_output=True,
                              text=True, env={**os.environ, **env_extra})
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = json.loads(proc.stdout)
        # repo-local manifest wins whole; xdg exemption never consulted.
        self.assertEqual(payload["unverified_paths"], ["src/feature.go"])

    def test_missing_manifest_nonempty_diff_fails(self) -> None:
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("no verifier manifest" in e for e in payload["errors"]))

    def test_manifest_present_empty_diff_short_circuits_without_running_command(self) -> None:
        # base == head, no staged/unstaged/untracked changes: nothing to verify,
        # so the configured command must never run. NONZERO_VERIFIER always
        # fails, so a nonzero result here would prove it ran anyway.
        self.install_verifier(NONZERO_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        self.head_sha = self.base_sha
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["relevant_paths"], [])
        self.assertEqual(payload["exemptions"], [])
        self.assertEqual(payload["errors"], [])

    def test_invalid_schema_version_fails(self) -> None:
        path = self.repo / ".agent-plugins/bento/bento/land-work/verifier.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 99, "command": [str(self.verifier_path)]}), encoding="utf-8")
        self.install_verifier(PASS_EMPTY_VERIFIER)
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("schema_version" in e for e in payload["errors"]))

    def test_empty_command_fails(self) -> None:
        path = self.repo / ".agent-plugins/bento/bento/land-work/verifier.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "command": []}), encoding="utf-8")
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("command" in e for e in payload["errors"]))

    # -- verifier result handling ---------------------------------------- #

    def test_one_passed_check_covers_relevant_diff(self) -> None:
        self.install_verifier(PASS_ONE_CHECK_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selected_check_count"], 1)

    def test_failed_selected_check_fails(self) -> None:
        self.install_verifier(FAILED_CHECK_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("did not pass" in e for e in payload["errors"]))

    def test_failed_status_fails(self) -> None:
        self.install_verifier(FAILED_STATUS_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("not 'passed'" in e for e in payload["errors"]))

    def test_invalid_result_json_fails(self) -> None:
        self.install_verifier(INVALID_JSON_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("not valid JSON" in e for e in payload["errors"]))

    def test_command_failure_fails(self) -> None:
        self.install_verifier(NONZERO_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("exited 3" in e for e in payload["errors"]))

    def test_command_timeout_fails(self) -> None:
        self.install_verifier(SLOW_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier(timeout="1")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(any("timed out" in e for e in payload["errors"]))

    # -- Git path union categories --------------------------------------- #

    def test_staged_change_enters_union(self) -> None:
        (self.worktree / "staged.txt").write_text("s\n", encoding="utf-8")
        git(self.worktree, "add", "staged.txt")
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        payload = json.loads(result.stdout)
        self.assertIn("staged.txt", payload["changed_paths"]["staged"])
        self.assertIn("staged.txt", payload["unverified_paths"])

    def test_unstaged_change_enters_union(self) -> None:
        # modify a tracked file without staging
        (self.worktree / "src" / "feature.go").write_text("package main // edit\n", encoding="utf-8")
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        payload = json.loads(result.stdout)
        self.assertIn("src/feature.go", payload["changed_paths"]["unstaged"])

    def test_untracked_nonignored_enters_union(self) -> None:
        (self.worktree / "untracked.txt").write_text("u\n", encoding="utf-8")
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        payload = json.loads(result.stdout)
        self.assertIn("untracked.txt", payload["changed_paths"]["untracked"])

    def test_ignored_file_excluded_from_union(self) -> None:
        (self.worktree / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        git(self.worktree, "add", ".gitignore")
        git(self.worktree, "commit", "-m", "gitignore")
        self.head_sha = git(self.worktree, "rev-parse", "HEAD").stdout.strip()
        (self.worktree / "ignored.txt").write_text("i\n", encoding="utf-8")
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[
                {"path": "src/feature.go", "reason": "gen"},
                {"path": ".gitignore", "reason": "gen"},
            ],
        )
        result = self.run_verifier()
        payload = json.loads(result.stdout)
        all_changed = sum(payload["changed_paths"].values(), [])
        self.assertNotIn("ignored.txt", all_changed)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_deleted_path_exemption_valid(self) -> None:
        # delete README.md on the branch; exemption for a deleted path is valid.
        git(self.worktree, "rm", "README.md")
        git(self.worktree, "commit", "-m", "remove readme")
        self.head_sha = git(self.worktree, "rev-parse", "HEAD").stdout.strip()
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[
                {"path": "README.md", "reason": "deleted, verified elsewhere"},
                {"path": "src/feature.go", "reason": "gen"},
            ],
        )
        result = self.run_verifier()
        payload = json.loads(result.stdout)
        self.assertIn("README.md", payload["changed_paths"]["committed"])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_renamed_path_both_sides_in_union(self) -> None:
        # Base must contain the pre-rename file for git to report a rename.
        self.base_sha = self.head_sha
        git(self.worktree, "mv", "src/feature.go", "src/renamed.go")
        git(self.worktree, "commit", "-m", "rename")
        self.head_sha = git(self.worktree, "rev-parse", "HEAD").stdout.strip()
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(command=[str(self.verifier_path)])
        result = self.run_verifier()
        payload = json.loads(result.stdout)
        committed = payload["changed_paths"]["committed"]
        self.assertIn("src/renamed.go", committed)
        self.assertIn("src/feature.go", committed)

    def test_mixed_union_only_some_exempt(self) -> None:
        (self.worktree / "untracked.txt").write_text("u\n", encoding="utf-8")
        self.install_verifier(PASS_ONE_CHECK_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "src/feature.go", "reason": "gen"}],
        )
        result = self.run_verifier()
        payload = json.loads(result.stdout)
        # feature.go exempt, untracked.txt still relevant → needs a passed check
        self.assertEqual(payload["exemptions"], ["src/feature.go"])
        self.assertIn("untracked.txt", payload["relevant_paths"])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_linked_worktree_index_not_primary(self) -> None:
        # A staged change in the primary checkout must NOT enter the candidate
        # (linked worktree) union.
        (self.repo / "primary-only.txt").write_text("p\n", encoding="utf-8")
        git(self.repo, "add", "primary-only.txt")
        self.install_verifier(PASS_EMPTY_VERIFIER)
        self.write_manifest(
            command=[str(self.verifier_path)],
            verified_noop=[{"path": "src/feature.go", "reason": "gen"}],
        )
        result = self.run_verifier()
        payload = json.loads(result.stdout)
        all_changed = sum(payload["changed_paths"].values(), [])
        self.assertNotIn("primary-only.txt", all_changed)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
