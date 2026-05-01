import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_SCRIPT = REPO_ROOT / "catalog/skills/launch-work/scripts/launch-work-log.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


def init_feature_repo(parent: Path, name: str = "repo") -> Path:
    repo = parent / name
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    git(repo, "checkout", "-b", "feature-x")
    return repo


def git_dir(cwd: Path) -> Path:
    return Path(git(cwd, "rev-parse", "--absolute-git-dir").stdout.strip())


def expected_log_path(repo: Path) -> Path:
    return git_dir(repo) / "launch-work" / "log.md"


class LaunchWorkLogInitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = init_feature_repo(Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_init_writes_log_under_git_dir_without_committing(self) -> None:
        result = run([str(LOG_SCRIPT), "init"], cwd=self.repo)
        payload = json.loads(result.stdout)
        log_path = expected_log_path(self.repo)

        self.assertTrue(log_path.is_file())
        self.assertEqual(payload["path"], str(log_path))
        self.assertEqual(payload["checkpoint"], "worktree-ready")

        body = log_path.read_text(encoding="utf-8")
        self.assertIn("checkpoint: worktree-ready", body)
        self.assertRegex(body, r"last-updated: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
        self.assertIn("## Next action", body)

        # No commit and no working-tree pollution.
        last_msg = git(self.repo, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(last_msg, "initial")
        status = git(self.repo, "status", "--porcelain").stdout.strip()
        self.assertEqual(status, "")
        self.assertFalse((self.repo / ".launch-work").exists())

    def test_init_refuses_when_log_already_exists(self) -> None:
        run([str(LOG_SCRIPT), "init"], cwd=self.repo)
        result = run([str(LOG_SCRIPT), "init"], cwd=self.repo, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    def test_init_refuses_on_primary_branch(self) -> None:
        git(self.repo, "checkout", "main")
        result = run([str(LOG_SCRIPT), "init"], cwd=self.repo, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("primary branch", result.stderr)


class LaunchWorkLogUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = init_feature_repo(Path(self.temp_dir.name))
        run([str(LOG_SCRIPT), "init"], cwd=self.repo)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_update_rewrites_checkpoint_without_committing(self) -> None:
        result = run([str(LOG_SCRIPT), "update", "--checkpoint", "deps-installed"], cwd=self.repo)
        self.assertEqual(result.returncode, 0)

        body = expected_log_path(self.repo).read_text(encoding="utf-8")
        self.assertIn("checkpoint: deps-installed", body)

        # Working tree must remain clean across updates.
        status = git(self.repo, "status", "--porcelain").stdout.strip()
        self.assertEqual(status, "")
        last_msg = git(self.repo, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(last_msg, "initial")

    def test_update_rejects_unknown_checkpoint(self) -> None:
        result = run(
            [str(LOG_SCRIPT), "update", "--checkpoint", "bogus"],
            cwd=self.repo,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown checkpoint", result.stderr)

    def test_update_with_slot_replaces_named_section(self) -> None:
        proc = subprocess.run(
            [
                str(LOG_SCRIPT),
                "update",
                "--checkpoint",
                "tests-green",
                "--slot",
                "next-action",
                "--content",
                "-",
            ],
            cwd=self.repo,
            input="Wire the new endpoint into routing.",
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(proc.returncode, 0)

        body = expected_log_path(self.repo).read_text(encoding="utf-8")
        self.assertIn("Wire the new endpoint into routing.", body)
        self.assertIn("checkpoint: tests-green", body)


class LaunchWorkLogReadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = init_feature_repo(Path(self.temp_dir.name))
        run([str(LOG_SCRIPT), "init"], cwd=self.repo)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_read_emits_header_fields_as_json(self) -> None:
        result = run([str(LOG_SCRIPT), "read"], cwd=self.repo)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["checkpoint"], "worktree-ready")
        self.assertRegex(payload["last_updated"], r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
        self.assertEqual(payload["path"], str(expected_log_path(self.repo)))

    def test_read_when_log_missing_exits_nonzero(self) -> None:
        expected_log_path(self.repo).unlink()
        result = run([str(LOG_SCRIPT), "read"], cwd=self.repo, check=False)
        self.assertNotEqual(result.returncode, 0)


class LaunchWorkLogLegacyFallbackTest(unittest.TestCase):
    """Branches in flight before the move out of the working tree must remain
    readable. 'read' falls back to <worktree>/.launch-work/log.md; 'update'
    refuses to silently mix locations."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = init_feature_repo(Path(self.temp_dir.name))
        legacy = self.repo / ".launch-work" / "log.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            "<!-- launch-work-log\n"
            "last-updated: 2026-01-15T10:00:00Z\n"
            "checkpoint: tests-green\n"
            "-->\n\n"
            "# Launch-Work Progress Log\n\n"
            "## Next action\n\nresume\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_read_falls_back_to_legacy_in_tree_path(self) -> None:
        result = run([str(LOG_SCRIPT), "read"], cwd=self.repo)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["checkpoint"], "tests-green")
        self.assertEqual(payload["path"], str(self.repo / ".launch-work/log.md"))

    def test_update_refuses_when_only_legacy_log_present(self) -> None:
        result = run(
            [str(LOG_SCRIPT), "update", "--checkpoint", "verification-passed"],
            cwd=self.repo,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy path", result.stderr)


if __name__ == "__main__":
    unittest.main()
