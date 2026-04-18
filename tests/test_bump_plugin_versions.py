import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import git


REPO_ROOT = Path(__file__).resolve().parents[1]


class BumpPluginVersionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()

        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Bump Versions Test")
        git(self.repo, "config", "user.email", "bump-versions@example.com")

        for relative_path in [
            "catalog",
            "scripts/build-plugins",
            "scripts/bump-plugin-versions",
            "tests/__init__.py",
            "tests/script_test_utils.py",
        ]:
            source = REPO_ROOT / relative_path
            target = self.repo / relative_path
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())

        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "initial plugin versions")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_bump(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "scripts/bump-plugin-versions", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_bumps_only_plugins_affected_by_changed_skill(self) -> None:
        versions_before = json.loads((self.repo / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))
        bento_before = versions_before["bento"]
        major, minor, patch = bento_before.split(".")
        bento_after = f"{major}.{minor}.{int(patch) + 1}"

        skill_path = self.repo / "catalog" / "skills" / "closure" / "SKILL.md"
        skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nMeaningful change.\n", encoding="utf-8")

        result = self.run_bump()
        payload = json.loads(result.stdout)
        versions = json.loads((self.repo / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["bumps"], {"bento": {"from": bento_before, "to": bento_after}})
        self.assertEqual(versions["bento"], bento_after)
        self.assertEqual(versions["trackers"], versions_before["trackers"])
        self.assertEqual(versions["stacks"], versions_before["stacks"])

    def test_build_script_change_bumps_all_plugins(self) -> None:
        versions_before = json.loads((self.repo / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))

        def minor_bump(v: str) -> str:
            major, minor, _patch = v.split(".")
            return f"{major}.{int(minor) + 1}.0"

        build_script = self.repo / "scripts" / "build-plugins"
        build_script.write_text(build_script.read_text(encoding="utf-8") + "\n# packaging change\n", encoding="utf-8")

        result = self.run_bump("--part", "minor")
        payload = json.loads(result.stdout)
        versions = json.loads((self.repo / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))

        self.assertEqual(
            payload["bumps"],
            {
                plugin: {"from": versions_before[plugin], "to": minor_bump(versions_before[plugin])}
                for plugin in versions_before
            },
        )
        self.assertEqual(set(payload["relevant_paths"]), {"scripts/build-plugins"})
        self.assertEqual(len(set(versions.values())), 1)  # all bumped to the same minor version

    def test_ignores_generated_outputs(self) -> None:
        versions_before = json.loads((self.repo / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))

        generated_manifest = self.repo / ".claude-plugin" / "marketplace.json"
        generated_manifest.parent.mkdir(parents=True, exist_ok=True)
        generated_manifest.write_text("{\"name\": \"generated\"}\n", encoding="utf-8")

        result = self.run_bump()
        payload = json.loads(result.stdout)
        versions = json.loads((self.repo / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["bumps"], {})
        self.assertEqual(versions, versions_before)

    def test_bootstrap_mode_when_version_file_has_no_committed_boundary(self) -> None:
        bootstrap_repo = Path(self.temp_dir.name) / "bootstrap-repo"
        bootstrap_repo.mkdir()

        git(bootstrap_repo, "init", "-b", "main")
        git(bootstrap_repo, "config", "user.name", "Bootstrap Versions Test")
        git(bootstrap_repo, "config", "user.email", "bootstrap-versions@example.com")
        (bootstrap_repo / "README.md").write_text("bootstrap\n", encoding="utf-8")
        git(bootstrap_repo, "add", "README.md")
        git(bootstrap_repo, "commit", "-m", "bootstrap root")

        shutil.copytree(REPO_ROOT / "catalog", bootstrap_repo / "catalog")
        (bootstrap_repo / "scripts").mkdir()
        (bootstrap_repo / "scripts" / "build-plugins").write_bytes((REPO_ROOT / "scripts" / "build-plugins").read_bytes())
        (bootstrap_repo / "scripts" / "bump-plugin-versions").write_bytes((REPO_ROOT / "scripts" / "bump-plugin-versions").read_bytes())

        result = subprocess.run(
            ["python3", "scripts/bump-plugin-versions"],
            cwd=bootstrap_repo,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        versions = json.loads((bootstrap_repo / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))

        versions_in_catalog = json.loads((REPO_ROOT / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))

        self.assertIsNone(payload["baseline_commit"])
        self.assertTrue(payload["bootstrap_required"])
        self.assertEqual(payload["bumps"], {})
        self.assertEqual(versions, versions_in_catalog)


if __name__ == "__main__":
    unittest.main()
