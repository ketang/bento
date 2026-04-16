import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
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

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_repo_generates_manifests_assets_and_claude_marketplace(self) -> None:
        self.module.build_repo(run_verification=False)

        plugin_dir = self.root / "plugins" / "bento-all"
        executable_helpers = [
            plugin_dir / "skills" / "build-vs-buy" / "scripts" / "build-vs-buy-discover.py",
            plugin_dir / "skills" / "closure" / "scripts" / "closure-scan.py",
            plugin_dir / "skills" / "generate-audit" / "scripts" / "audit-discover.py",
            plugin_dir / "skills" / "land-work" / "scripts" / "land-work-prepare.py",
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
        self.assertEqual(codex_manifest["version"], versions["bento-all"])
        self.assertEqual(codex_manifest["skills"], "./skills/")
        self.assertEqual(codex_manifest["interface"]["displayName"], "Bento All")
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
        codex_manifest = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("skills", codex_manifest)
        self.assertEqual(codex_manifest["version"], "1.0.1")

    def test_build_repo_copies_red_green_tdd_guidance_into_generated_skills(self) -> None:
        self.module.build_repo(run_verification=False)

        plugin_dir = self.root / "plugins" / "bento-all" / "skills"
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

    def test_external_plugins_appear_in_marketplace_with_github_source(self) -> None:
        self.module.build_repo(run_verification=False)

        marketplace = json.loads(
            (self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        plugin_names = [p["name"] for p in marketplace["plugins"]]
        self.assertIn("bugshot", plugin_names)

        bugshot = next(p for p in marketplace["plugins"] if p["name"] == "bugshot")
        self.assertEqual(bugshot["source"], {"source": "github", "repo": "ketang/bugshot"})
        self.assertNotIn("version", bugshot)

    def test_external_plugins_have_ref_field(self) -> None:
        for ext in self.module.EXTERNAL_PLUGINS:
            self.assertIn("ref", ext, f"External plugin {ext['name']} missing 'ref' field")

    def test_external_plugins_are_not_built_locally(self) -> None:
        self.module.build_repo(run_verification=False)

        self.assertFalse((self.root / "plugins" / "bugshot").exists())

    def test_external_plugin_dirs_not_pruned(self) -> None:
        ext_dir = self.root / "plugins" / "bugshot"
        ext_dir.mkdir(parents=True)
        (ext_dir / "marker.txt").write_text("external\n", encoding="utf-8")

        self.module.build_repo(run_verification=False)

        self.assertTrue(ext_dir.exists())

    def test_build_repo_prunes_stale_generated_plugin_directories(self) -> None:
        stale_dir = self.root / "plugins" / "obsolete-pack"
        stale_dir.mkdir(parents=True)
        (stale_dir / "orphan.txt").write_text("stale\n", encoding="utf-8")

        self.module.build_repo(run_verification=False)

        self.assertFalse(stale_dir.exists())


if __name__ == "__main__":
    unittest.main()
