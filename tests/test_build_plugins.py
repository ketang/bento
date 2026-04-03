import importlib.machinery
import importlib.util
import json
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
        self.module.PLUGINS_DIR = self.root / "plugins"
        self.module.CLAUDE_MARKETPLACE_FILE = self.root / ".claude-plugin" / "marketplace.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_repo_generates_manifests_assets_and_claude_marketplace(self) -> None:
        self.module.build_repo(run_verification=False)

        plugin_dir = self.root / "plugins" / "bento-all"
        self.assertTrue((plugin_dir / ".claude-plugin" / "plugin.json").exists())
        self.assertTrue((plugin_dir / ".codex-plugin" / "plugin.json").exists())
        self.assertTrue((plugin_dir / "skills" / "closure" / "SKILL.md").exists())

        codex_manifest = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
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
        self.assertEqual(claude_marketplace["plugins"][2]["source"], "./plugins/stacks")

    def test_build_repo_prunes_stale_generated_plugin_directories(self) -> None:
        stale_dir = self.root / "plugins" / "obsolete-pack"
        stale_dir.mkdir(parents=True)
        (stale_dir / "orphan.txt").write_text("stale\n", encoding="utf-8")

        self.module.build_repo(run_verification=False)

        self.assertFalse(stale_dir.exists())


if __name__ == "__main__":
    unittest.main()
