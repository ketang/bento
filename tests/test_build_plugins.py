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

        claude_bento = self.root / "plugins" / "claude" / "bento"
        codex_bento = self.root / "plugins" / "codex" / "bento"
        executable_helpers = [
            claude_bento / "skills" / "build-vs-buy" / "scripts" / "build-vs-buy-discover.py",
            claude_bento / "skills" / "closure" / "scripts" / "closure-scan.py",
            claude_bento / "skills" / "expedition" / "scripts" / "expedition.py",
            claude_bento / "skills" / "generate-audit" / "scripts" / "audit-discover.py",
            claude_bento / "skills" / "land-work" / "scripts" / "land-work-create-preview.py",
            claude_bento / "skills" / "land-work" / "scripts" / "land-work-prepare.py",
            claude_bento / "skills" / "land-work" / "scripts" / "land-work-verify-landing.py",
            claude_bento / "skills" / "land-work" / "scripts" / "land-work-verify-lease.py",
            claude_bento / "skills" / "launch-work" / "scripts" / "launch-work-bootstrap.py",
            claude_bento / "skills" / "launch-work" / "scripts" / "launch-work-verify.py",
            claude_bento / "skills" / "swarm" / "scripts" / "swarm-discover.py",
            claude_bento / "skills" / "swarm" / "scripts" / "swarm-state.py",
            claude_bento / "skills" / "swarm" / "scripts" / "swarm-triage.py",
            claude_bento / "skills" / "swarm" / "scripts" / "swarm-worktree-verify.py",
        ]
        self.assertTrue((claude_bento / ".claude-plugin" / "plugin.json").exists())
        self.assertFalse((claude_bento / ".codex-plugin").exists())
        self.assertTrue((codex_bento / ".codex-plugin" / "plugin.json").exists())
        self.assertFalse((codex_bento / ".claude-plugin").exists())
        self.assertTrue((claude_bento / "skills" / "closure" / "SKILL.md").exists())

        for helper in executable_helpers:
            self.assertTrue(helper.exists(), helper)
            self.assertTrue(os.access(helper, os.X_OK), helper)

        versions = json.loads((REPO_ROOT / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))
        codex_manifest = json.loads((codex_bento / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(codex_manifest["version"], versions["bento"])
        self.assertEqual(codex_manifest["skills"], "./skills/")
        self.assertEqual(codex_manifest["interface"]["displayName"], "Bento")
        self.assertEqual(len(codex_manifest["interface"]["defaultPrompt"]), 3)
        self.assertEqual(codex_manifest["interface"]["composerIcon"], "./assets/icon.png")
        self.assertEqual(codex_manifest["interface"]["screenshots"][2], "./assets/screenshot-3.png")
        self.assertEqual(list(claude_bento.rglob("*.pyc")), [])
        self.assertEqual([path.name for path in claude_bento.rglob("__pycache__")], [])

        for asset_name in ["icon.png", "logo.png", "screenshot-1.png", "screenshot-2.png", "screenshot-3.png"]:
            asset = claude_bento / "assets" / asset_name
            self.assertTrue(asset.exists(), asset_name)
            self.assertGreater(asset.stat().st_size, 0)

        claude_marketplace = json.loads((self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(claude_marketplace["plugins"][1]["name"], "trackers")
        self.assertEqual(claude_marketplace["plugins"][1]["version"], versions["trackers"])
        self.assertEqual(claude_marketplace["plugins"][2]["source"], "./plugins/claude/stacks")
        self.assertEqual(claude_marketplace["plugins"][3]["name"], "session-id")

    def test_session_id_plugin_is_claude_only(self) -> None:
        self.module.build_repo(run_verification=False)

        claude_session = self.root / "plugins" / "claude" / "session-id"
        codex_session = self.root / "plugins" / "codex" / "session-id"

        self.assertTrue(claude_session.exists())
        # Codex output is skipped entirely because session-id's only artifact
        # (a SessionStart hook) is Claude-only by default.
        self.assertFalse(codex_session.exists())

        self.assertFalse((claude_session / "skills").exists())

        hooks_json = claude_session / "hooks" / "hooks.json"
        self.assertTrue(hooks_json.exists())
        hooks = json.loads(hooks_json.read_text(encoding="utf-8"))
        self.assertIn("SessionStart", hooks["hooks"])

        hook_script = claude_session / "hooks" / "scripts" / "session-start.py"
        self.assertTrue(hook_script.exists())
        self.assertTrue(os.access(hook_script, os.X_OK))

    def test_bento_claude_only_hook_absent_from_codex_materialization(self) -> None:
        self.module.build_repo(run_verification=False)

        claude_bento_hooks = self.root / "plugins" / "claude" / "bento" / "hooks"
        codex_bento = self.root / "plugins" / "codex" / "bento"

        # The auto-allow hook ships with bento; it's Claude-only by hook default.
        self.assertTrue((claude_bento_hooks / "hooks.json").exists())
        self.assertTrue((claude_bento_hooks / "scripts" / "auto-allow.py").exists())
        self.assertFalse((codex_bento / "hooks").exists())

    def test_session_id_not_in_claude_marketplace_when_claude_empty(self) -> None:
        # Force session-id to have no Claude artifacts, confirm it drops out
        # of the Claude marketplace entries.
        self.module.HOOK_PLATFORM_DEFAULT = ("codex",)

        # Rebuild with the flipped default.
        self.module.build_repo(run_verification=False)

        claude_marketplace = json.loads(
            (self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        plugin_names = [p["name"] for p in claude_marketplace["plugins"] if "version" in p]
        self.assertNotIn("session-id", plugin_names)

    def test_packaging_sidecar_narrows_skill_to_codex_only(self) -> None:
        # Add a codex-only sidecar to the closure skill, confirm it disappears
        # from the Claude bento build and remains in Codex.
        packaging = self.root / "catalog" / "skills" / "closure" / "packaging.json"
        packaging.write_text(json.dumps({"platforms": ["codex"]}), encoding="utf-8")

        self.module.build_repo(run_verification=False)

        claude_closure = self.root / "plugins" / "claude" / "bento" / "skills" / "closure"
        codex_closure = self.root / "plugins" / "codex" / "bento" / "skills" / "closure"

        self.assertFalse(claude_closure.exists())
        self.assertTrue(codex_closure.exists())

    def test_packaging_sidecar_file_not_copied_into_output(self) -> None:
        packaging = self.root / "catalog" / "skills" / "closure" / "packaging.json"
        packaging.write_text(json.dumps({"platforms": ["claude", "codex"]}), encoding="utf-8")

        self.module.build_repo(run_verification=False)

        for platform in ("claude", "codex"):
            copied = self.root / "plugins" / platform / "bento" / "skills" / "closure" / "packaging.json"
            self.assertFalse(copied.exists(), copied)

    def test_invalid_platform_in_sidecar_raises(self) -> None:
        packaging = self.root / "catalog" / "skills" / "closure" / "packaging.json"
        packaging.write_text(json.dumps({"platforms": ["klingon"]}), encoding="utf-8")

        with self.assertRaises(SystemExit):
            self.module.build_repo(run_verification=False)

    def test_build_repo_copies_red_green_tdd_guidance_into_generated_skills(self) -> None:
        self.module.build_repo(run_verification=False)

        skills_dir = self.root / "plugins" / "claude" / "bento" / "skills"
        expected_phrases = {
            "launch-work": "For new work and behavioral changes with feasible automated coverage, use a red/green workflow",
            "react-vite-mantine": "write or update a component test so it fails before implementing the change",
            "go-pgx-goose": "write or update the relevant test so it fails before implementing the change",
            "graphql-gqlgen-gql-tada": "write or update the relevant backend or frontend test so it fails before implementing the change",
        }

        for skill_name, expected_phrase in expected_phrases.items():
            skill_text = (skills_dir / skill_name / "SKILL.md").read_text(encoding="utf-8")
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

    def test_bugshot_external_skill_not_built_as_top_level_plugin(self) -> None:
        self.module.build_repo(run_verification=False)

        for platform in ("claude", "codex"):
            self.assertFalse((self.root / "plugins" / platform / "bugshot").exists())

    def test_build_repo_prunes_stale_generated_plugin_directories(self) -> None:
        stale_dir = self.root / "plugins" / "claude" / "obsolete-pack"
        stale_dir.mkdir(parents=True)
        (stale_dir / "orphan.txt").write_text("stale\n", encoding="utf-8")

        self.module.build_repo(run_verification=False)

        self.assertFalse(stale_dir.exists())

    def test_build_repo_includes_dev_skill_in_claude_bento_plugin(self) -> None:
        self.module.build_repo(run_verification=False)
        dev_skill_md = (
            self.root / "plugins" / "claude" / "bento" / "skills" / "dev-skill" / "SKILL.md"
        )
        self.assertTrue(dev_skill_md.exists(), "dev-skill SKILL.md must be present in claude bento plugin")

    def test_dev_skill_is_excluded_from_codex_bento_plugin(self) -> None:
        self.module.build_repo(run_verification=False)
        codex_path = self.root / "plugins" / "codex" / "bento" / "skills" / "dev-skill"
        self.assertFalse(codex_path.exists(), "dev-skill must not appear in codex bento plugin")


if __name__ == "__main__":
    unittest.main()
