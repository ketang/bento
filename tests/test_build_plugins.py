import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "build-plugins"


def load_build_plugins_module():
    loader = importlib.machinery.SourceFileLoader("build_plugins", str(SCRIPT))
    spec = importlib.util.spec_from_loader("build_plugins", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for build-plugins")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class BuildPluginsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "repo"
        shutil.copytree(REPO_ROOT / "catalog", self.root / "catalog")
        (self.root / "plugins").mkdir(parents=True)
        self.module = load_build_plugins_module()
        self.module.ROOT_DIR = self.root
        self.module.CATALOG_DIR = self.root / "catalog" / "skills"
        self.module.HOOKS_CATALOG_DIR = self.root / "catalog" / "hooks"
        self.module.PLUGINS_DIR = self.root / "plugins"
        self.module.CLAUDE_MARKETPLACE_FILE = self.root / ".claude-plugin" / "marketplace.json"
        self.module.EXTERNAL_SKILLS = {}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_repo_generates_manifests_assets_and_claude_marketplace(self) -> None:
        self.module.build_repo(run_verification=False)

        plugin_dir = self.root / "plugins" / "bento"
        executable_helpers = [
            plugin_dir / "skills" / "build-vs-buy" / "scripts" / "build-vs-buy-discover.py",
            plugin_dir / "skills" / "closure" / "scripts" / "closure-scan.py",
            plugin_dir / "skills" / "expedition" / "scripts" / "expedition.py",
            plugin_dir / "skills" / "generate-audit" / "scripts" / "audit-discover.py",
            plugin_dir / "skills" / "land-work" / "scripts" / "land-work-create-preview.py",
            plugin_dir / "skills" / "land-work" / "scripts" / "land-work-prepare.py",
            plugin_dir / "skills" / "land-work" / "scripts" / "land-work-verify-landing.py",
            plugin_dir / "skills" / "land-work" / "scripts" / "land-work-verify-lease.py",
            plugin_dir / "skills" / "launch-work" / "scripts" / "launch-work-bootstrap.py",
            plugin_dir / "skills" / "launch-work" / "scripts" / "launch-work-verify.py",
            plugin_dir / "skills" / "swarm" / "scripts" / "swarm-discover.py",
            plugin_dir / "skills" / "swarm" / "scripts" / "swarm-state.py",
            plugin_dir / "skills" / "swarm" / "scripts" / "swarm-triage.py",
            plugin_dir / "skills" / "swarm" / "scripts" / "swarm-worktree-verify.py",
        ]
        self.assertTrue((plugin_dir / ".claude-plugin" / "plugin.json").exists())
        self.assertTrue((plugin_dir / ".codex-plugin" / "plugin.json").exists())
        self.assertTrue((plugin_dir / "skills" / "closure" / "SKILL.md").exists())

        for helper in executable_helpers:
            self.assertTrue(helper.exists(), helper)
            self.assertTrue(os.access(helper, os.X_OK), helper)

        versions = json.loads((REPO_ROOT / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))
        codex_manifest = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(codex_manifest["version"], versions["bento"])
        self.assertEqual(codex_manifest["skills"], "./skills/")
        self.assertEqual(codex_manifest["interface"]["displayName"], "Bento")
        self.assertEqual(len(codex_manifest["interface"]["defaultPrompt"]), 3)
        self.assertEqual(codex_manifest["interface"]["composerIcon"], "./assets/icon.png")
        self.assertEqual(codex_manifest["interface"]["screenshots"][2], "./assets/screenshot-3.png")
        self.assertEqual(list(plugin_dir.rglob("*.pyc")), [])
        self.assertEqual([path.name for path in plugin_dir.rglob("__pycache__")], [])

        for asset_name in ["icon.png", "logo.png", "screenshot-1.png", "screenshot-2.png", "screenshot-3.png"]:
            asset = plugin_dir / "assets" / asset_name
            self.assertTrue(asset.exists(), asset_name)
            self.assertGreater(asset.stat().st_size, 0)

        claude_marketplace = json.loads((self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(claude_marketplace["plugins"][1]["name"], "trackers")
        self.assertEqual(claude_marketplace["plugins"][1]["version"], versions["trackers"])
        self.assertEqual(claude_marketplace["plugins"][2]["source"], "./plugins/stacks")
        self.assertEqual(claude_marketplace["plugins"][3]["name"], "session-id")

    def test_session_id_plugin_has_hooks_and_no_skills_dir(self) -> None:
        self.module.build_repo(run_verification=False)

        plugin_dir = self.root / "plugins" / "session-id"
        self.assertTrue(plugin_dir.exists())

        # no skills directory for a hook-only plugin
        self.assertFalse((plugin_dir / "skills").exists())

        # hooks directory and config present
        hooks_json = plugin_dir / "hooks" / "hooks.json"
        self.assertTrue(hooks_json.exists())
        hooks = json.loads(hooks_json.read_text(encoding="utf-8"))
        self.assertIn("SessionStart", hooks["hooks"])

        # hook script is executable
        hook_script = plugin_dir / "hooks" / "scripts" / "session-start.py"
        self.assertTrue(hook_script.exists())
        self.assertTrue(os.access(hook_script, os.X_OK))

        # codex manifest has no "skills" field
        versions = json.loads((REPO_ROOT / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))
        codex_manifest = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("skills", codex_manifest)
        self.assertEqual(codex_manifest["version"], versions["session-id"])

    def test_build_repo_copies_red_green_tdd_guidance_into_generated_skills(self) -> None:
        self.module.build_repo(run_verification=False)

        plugin_dir = self.root / "plugins" / "bento" / "skills"
        expected_phrases = {
            "launch-work": "For new work and behavioral changes with feasible automated coverage, use a red/green workflow",
            "react-vite-mantine": "write or update a component test so it fails before implementing the change",
            "go-pgx-goose": "write or update the relevant test so it fails before implementing the change",
            "graphql-gqlgen-gql-tada": "write or update the relevant backend or frontend test so it fails before implementing the change",
        }

        for skill_name, expected_phrase in expected_phrases.items():
            skill_text = (plugin_dir / skill_name / "SKILL.md").read_text(encoding="utf-8")
            normalized_skill_text = re.sub(r"\s+", " ", skill_text)
            self.assertIn(expected_phrase, normalized_skill_text)

    def test_external_skills_registry_declares_bugshot_under_bento(self) -> None:
        module = load_build_plugins_module()
        entries = module.EXTERNAL_SKILLS.get("bento", [])
        bugshot = next((e for e in entries if e["name"] == "bugshot"), None)
        self.assertIsNotNone(bugshot, "bugshot should be registered as an external skill of bento")
        self.assertEqual(bugshot["repo"], "ketang/bugshot")
        self.assertRegex(bugshot["ref"], r"^[0-9a-f]{40}$", "ref should be a pinned commit SHA")

    def test_fetch_external_skill_places_skill_md_at_destination_root(self) -> None:
        fake_repo = self._build_fake_skill_repo("bugshot")
        destination = self.root / "plugins" / "bento" / "skills" / "bugshot"
        self.module.fetch_external_skill(destination, str(fake_repo), "HEAD")

        self.assertTrue((destination / "SKILL.md").exists())
        self.assertFalse((destination / ".git").exists())

    def test_fetch_external_skill_include_restricts_copied_paths(self) -> None:
        fake_repo = self._build_fake_skill_repo("bugshot")
        (fake_repo / "extra.py").write_text("# drop me\n", encoding="utf-8")
        (fake_repo / "docs").mkdir()
        (fake_repo / "docs" / "notes.md").write_text("ignore\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(fake_repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(fake_repo), "commit", "--quiet", "-m", "add bloat"], check=True)

        destination = self.root / "plugins" / "bento" / "skills" / "bugshot"
        self.module.fetch_external_skill(
            destination, str(fake_repo), "HEAD", include=["SKILL.md"]
        )

        self.assertTrue((destination / "SKILL.md").exists())
        self.assertFalse((destination / "extra.py").exists())
        self.assertFalse((destination / "docs").exists())

    def test_fetch_external_skill_raises_when_skill_md_missing(self) -> None:
        empty_repo = Path(self.temp_dir.name) / "empty-repo"
        empty_repo.mkdir()
        (empty_repo / "README.md").write_text("no skill here\n", encoding="utf-8")
        subprocess.run(["git", "init", "--quiet"], cwd=empty_repo, check=True)
        subprocess.run(["git", "-C", str(empty_repo), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(empty_repo), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(empty_repo), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(empty_repo), "commit", "--quiet", "-m", "init"], check=True)

        destination = self.root / "plugins" / "bento" / "skills" / "bogus"
        with self.assertRaises(SystemExit):
            self.module.fetch_external_skill(destination, str(empty_repo), "HEAD")

    def _build_fake_skill_repo(self, name: str) -> Path:
        repo = Path(self.temp_dir.name) / f"fake-{name}.git-src"
        repo.mkdir()
        (repo / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: fake {name} skill\n---\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "SKILL.md"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--quiet", "-m", "init"],
            check=True,
        )
        return repo

    def test_build_repo_prunes_stale_generated_plugin_directories(self) -> None:
        stale_dir = self.root / "plugins" / "obsolete-pack"
        stale_dir.mkdir(parents=True)
        (stale_dir / "orphan.txt").write_text("stale\n", encoding="utf-8")

        self.module.build_repo(run_verification=False)

        self.assertFalse(stale_dir.exists())


if __name__ == "__main__":
    unittest.main()
