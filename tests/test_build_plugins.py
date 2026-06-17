import contextlib
import importlib.machinery
import importlib.util
import io
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

    @contextlib.contextmanager
    def maybe_skip_assets(self, *, enabled: bool):
        original = self.module.write_assets
        if not enabled:
            self.module.write_assets = lambda plugin, platform: None
        try:
            yield
        finally:
            self.module.write_assets = original

    def build_repo(self, *, with_assets: bool = False) -> None:
        with self.maybe_skip_assets(enabled=with_assets):
            self.module.build_repo(run_verification=False)

    def test_build_repo_generates_manifests_assets_and_claude_marketplace(self) -> None:
        self.build_repo(with_assets=True)

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
        self.assertTrue((claude_bento / "skills" / "generate-web-demo" / "SKILL.md").exists())
        self.assertTrue((claude_bento / "skills" / "maintain-web-demo" / "SKILL.md").exists())
        self.assertTrue((codex_bento / "skills" / "generate-web-demo" / "SKILL.md").exists())
        self.assertTrue((codex_bento / "skills" / "maintain-web-demo" / "SKILL.md").exists())

        for helper in executable_helpers:
            self.assertTrue(helper.exists(), helper)
            self.assertTrue(os.access(helper, os.X_OK), helper)

        versions = json.loads((REPO_ROOT / "catalog" / "plugin-versions.json").read_text(encoding="utf-8"))
        codex_manifest = json.loads((codex_bento / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(codex_manifest["version"], versions["bento"])
        self.assertEqual(codex_manifest["skills"], "./skills/")
        self.assertEqual(codex_manifest["hooks"], "./hooks/hooks.json")
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
        plugins_by_name = {p["name"]: p for p in claude_marketplace["plugins"]}
        self.assertIn("trackers", plugins_by_name)
        self.assertEqual(plugins_by_name["trackers"]["version"], versions["trackers"])
        self.assertEqual(plugins_by_name["stacks"]["source"], "./plugins/claude/stacks")
        self.assertIn("session-id", plugins_by_name)

    def test_session_id_plugin_is_claude_only(self) -> None:
        self.build_repo()

        claude_session = self.root / "plugins" / "claude" / "session-id"
        codex_session = self.root / "plugins" / "codex" / "session-id"

        self.assertTrue(claude_session.exists())
        # Codex output is skipped entirely because session-id's only artifact
        # (a SessionStart hook) has only a Claude peer source.
        self.assertFalse(codex_session.exists())

        self.assertFalse((claude_session / "skills").exists())

        hooks_json = claude_session / "hooks" / "hooks.json"
        self.assertTrue(hooks_json.exists())
        hooks = json.loads(hooks_json.read_text(encoding="utf-8"))
        self.assertIn("SessionStart", hooks["hooks"])

        hook_script = claude_session / "hooks" / "scripts" / "session-start.py"
        self.assertTrue(hook_script.exists())
        self.assertTrue(os.access(hook_script, os.X_OK))

    def test_intent_stories_trio_removed_from_build(self) -> None:
        self.module.build_repo(run_verification=False)

        self.assertNotIn("intent-stories", self.module.PLUGIN_ORDER)
        self.assertNotIn("intent-stories", self.module.PLUGIN_DEFS)

        for skill in (
            "generate-intent-stories",
            "audit-intent-stories",
            "update-intent-stories",
        ):
            self.assertFalse(
                (self.root / "catalog" / "skills" / skill).exists(),
                f"canonical skill {skill} must be removed",
            )

        for platform in ("claude", "codex"):
            plugin = self.root / "plugins" / platform / "intent-stories"
            self.assertFalse(plugin.exists(), f"{platform}: intent-stories plugin must not be built")
            for skill in (
                "generate-intent-stories",
                "audit-intent-stories",
                "update-intent-stories",
            ):
                bundled = self.root / "plugins" / platform / "bento" / "skills" / skill
                self.assertFalse(bundled.exists(), f"{platform}:{skill} must not be bundled in bento")

        claude_marketplace = json.loads(
            (self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        plugin_names = [p["name"] for p in claude_marketplace["plugins"]]
        self.assertNotIn("intent-stories", plugin_names)

    def test_bento_hook_peers_materialize_for_claude_and_codex(self) -> None:
        self.build_repo()

        claude_bento_hooks = self.root / "plugins" / "claude" / "bento" / "hooks"
        codex_bento = self.root / "plugins" / "codex" / "bento"
        codex_bento_hooks = codex_bento / "hooks"
        codex_manifest = json.loads((codex_bento / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        claude_hooks = json.loads((claude_bento_hooks / "hooks.json").read_text(encoding="utf-8"))
        codex_hooks = json.loads((codex_bento_hooks / "hooks.json").read_text(encoding="utf-8"))

        self.assertTrue((claude_bento_hooks / "hooks.json").exists())
        self.assertTrue((claude_bento_hooks / "scripts" / "auto-allow.py").exists())
        self.assertTrue((claude_bento_hooks / "scripts" / "ensure-worktree-permissions.py").exists())
        self.assertTrue((claude_bento_hooks / "scripts" / "require-worktree.sh").exists())
        self.assertTrue((claude_bento_hooks / "scripts" / "register-require-worktree-hook.py").exists())
        self.assertIn("PreToolUse", claude_hooks["hooks"])
        self.assertIn(
            "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/auto-allow.py bento ${CLAUDE_PLUGIN_ROOT}",
            [
                hook["command"]
                for entry in claude_hooks["hooks"]["PreToolUse"]
                for hook in entry["hooks"]
            ],
        )
        self.assertIn(
            "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/register-require-worktree-hook.py ${CLAUDE_PLUGIN_ROOT}",
            [
                hook["command"]
                for entry in claude_hooks["hooks"]["SessionStart"]
                for hook in entry["hooks"]
            ],
        )

        self.assertEqual(codex_manifest["hooks"], "./hooks/hooks.json")
        self.assertTrue((codex_bento_hooks / "scripts" / "permission-request.py").exists())
        self.assertTrue((codex_bento_hooks / "scripts" / "seed-agent-plugins.py").exists())
        self.assertFalse((codex_bento_hooks / "scripts" / "auto-allow.py").exists())
        self.assertFalse((codex_bento_hooks / "scripts" / "ensure-worktree-permissions.py").exists())
        # bento-gs7: the register script writes to ~/.claude/settings.json
        # using whatever plugin root it is invoked with. The Codex build must
        # not ship the script and must not list it in hooks.json, otherwise a
        # Codex SessionStart will plant Codex cache paths into Claude Code's
        # settings file (the "command not found" cross-runtime dispatch bug).
        self.assertFalse(
            (codex_bento_hooks / "scripts" / "register-require-worktree-hook.py").exists(),
            msg="Codex plugin must not ship the Claude-only register-require-worktree-hook.py",
        )
        self.assertFalse(
            (codex_bento_hooks / "scripts" / "require-worktree.sh").exists(),
            msg="Codex plugin must not ship the Claude-only require-worktree.sh",
        )
        codex_session_commands = [
            hook["command"]
            for entry in codex_hooks["hooks"].get("SessionStart", [])
            for hook in entry["hooks"]
        ]
        for cmd in codex_session_commands:
            self.assertNotIn(
                "register-require-worktree-hook",
                cmd,
                msg=(
                    "Codex hooks.json SessionStart must not reference the "
                    f"Claude-only register script (bento-gs7); got: {cmd!r}"
                ),
            )
        self.assertIn("PermissionRequest", codex_hooks["hooks"])
        self.assertIn(
            "${PLUGIN_ROOT}/hooks/scripts/permission-request.py bento ${PLUGIN_ROOT}",
            [
                hook["command"]
                for entry in codex_hooks["hooks"]["PermissionRequest"]
                for hook in entry["hooks"]
            ],
        )

    def test_bento_claude_plugin_packages_telemetry_hook_support(self) -> None:
        self.build_repo()

        claude_bento_hooks = self.root / "plugins" / "claude" / "bento" / "hooks"
        hooks_json = json.loads((claude_bento_hooks / "hooks.json").read_text(encoding="utf-8"))
        post_tool_use = hooks_json["hooks"]["PostToolUse"]
        commands = [
            hook["command"]
            for entry in post_tool_use
            if entry.get("matcher") == "Bash"
            for hook in entry["hooks"]
        ]

        self.assertTrue((claude_bento_hooks / "scripts" / "auto-allow.py").exists())
        self.assertTrue((claude_bento_hooks / "scripts" / "seed-agent-plugins.py").exists())
        self.assertTrue((claude_bento_hooks / "scripts" / "ensure-worktree-permissions.py").exists())
        self.assertIn(
            "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/record-bash.py",
            commands,
        )
        self.assertTrue((claude_bento_hooks / "scripts" / "bento_telemetry.py").exists())
        for script_name in ["record-bash.py", "bento-telemetry.py"]:
            script = claude_bento_hooks / "scripts" / script_name
            self.assertTrue(script.exists(), script)
            self.assertTrue(os.access(script, os.X_OK), script)

    def test_codex_bento_plugin_packages_codex_telemetry_hook_support(self) -> None:
        self.build_repo()

        codex_bento_hooks = self.root / "plugins" / "codex" / "bento" / "hooks"
        hooks_json = json.loads((codex_bento_hooks / "hooks.json").read_text(encoding="utf-8"))
        post_tool_use = hooks_json["hooks"]["PostToolUse"]
        commands = [
            hook["command"]
            for entry in post_tool_use
            if entry.get("matcher") == "Bash"
            for hook in entry["hooks"]
        ]

        self.assertIn(
            "${PLUGIN_ROOT}/hooks/scripts/record-bash.py",
            commands,
        )
        self.assertTrue((codex_bento_hooks / "scripts" / "bento_telemetry.py").exists())
        for script_name in ["record-bash.py", "bento-telemetry.py"]:
            script = codex_bento_hooks / "scripts" / script_name
            self.assertTrue(script.exists(), script)
            self.assertTrue(os.access(script, os.X_OK), script)

    def test_hook_without_platform_peer_is_not_materialized(self) -> None:
        hook_dir = self.root / "catalog" / "hooks" / "experimental"
        hook_dir.mkdir(parents=True)
        (hook_dir / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
        self.module.PLUGIN_DEFS["bento"]["hooks"] = ["experimental"]

        self.build_repo()

        self.assertTrue((self.root / "plugins" / "claude" / "bento").exists())
        self.assertTrue((self.root / "plugins" / "codex" / "bento").exists())
        self.assertFalse((self.root / "plugins" / "claude" / "bento" / "hooks").exists())
        self.assertFalse((self.root / "plugins" / "codex" / "bento" / "hooks").exists())

    def test_packaging_sidecar_narrows_skill_to_codex_only(self) -> None:
        # Add a codex-only sidecar to the closure skill, confirm it disappears
        # from the Claude bento build and remains in Codex.
        packaging = self.root / "catalog" / "skills" / "closure" / "packaging.json"
        packaging.write_text(json.dumps({"platforms": ["codex"]}), encoding="utf-8")

        self.build_repo()

        claude_closure = self.root / "plugins" / "claude" / "bento" / "skills" / "closure"
        codex_closure = self.root / "plugins" / "codex" / "bento" / "skills" / "closure"

        self.assertFalse(claude_closure.exists())
        self.assertTrue(codex_closure.exists())

    def test_packaging_sidecar_file_not_copied_into_output(self) -> None:
        packaging = self.root / "catalog" / "skills" / "closure" / "packaging.json"
        packaging.write_text(json.dumps({"platforms": ["claude", "codex"]}), encoding="utf-8")

        self.build_repo()

        for platform in ("claude", "codex"):
            copied = self.root / "plugins" / platform / "bento" / "skills" / "closure" / "packaging.json"
            self.assertFalse(copied.exists(), copied)

    def test_platform_overlay_is_composed_into_generated_skill_md(self) -> None:
        skill_dir = self.root / "catalog" / "skills" / "closure"
        (skill_dir / "CLAUDE.md").write_text("Claude-only requirements.\n", encoding="utf-8")
        (skill_dir / "CODEX.md").write_text("Codex-only requirements.\n", encoding="utf-8")

        self.build_repo()

        claude_text = (
            self.root / "plugins" / "claude" / "bento" / "skills" / "closure" / "SKILL.md"
        ).read_text(encoding="utf-8")
        codex_text = (
            self.root / "plugins" / "codex" / "bento" / "skills" / "closure" / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("# Closure", claude_text)
        self.assertIn("Claude-only requirements.", claude_text)
        self.assertNotIn("Codex-only requirements.", claude_text)
        self.assertIn("# Closure", codex_text)
        self.assertIn("Codex-only requirements.", codex_text)
        self.assertNotIn("Claude-only requirements.", codex_text)

    def test_platform_overlay_sidecars_are_not_copied_into_output(self) -> None:
        skill_dir = self.root / "catalog" / "skills" / "closure"
        (skill_dir / "CLAUDE.md").write_text("Claude-only requirements.\n", encoding="utf-8")
        (skill_dir / "CODEX.md").write_text("Codex-only requirements.\n", encoding="utf-8")

        self.build_repo()

        for platform in ("claude", "codex"):
            generated_skill = self.root / "plugins" / platform / "bento" / "skills" / "closure"
            self.assertFalse((generated_skill / "CLAUDE.md").exists())
            self.assertFalse((generated_skill / "CODEX.md").exists())

    def test_build_repo_excludes_tests_and_non_runtime_docs_from_plugin_output(self) -> None:
        skill_dir = self.root / "catalog" / "skills" / "closure"
        (skill_dir / "tests").mkdir()
        (skill_dir / "tests" / "test_closure.py").write_text("assert False\n", encoding="utf-8")
        (skill_dir / "scripts" / "closure_test.py").write_text("assert False\n", encoding="utf-8")
        (skill_dir / "README.md").write_text("source-only notes\n", encoding="utf-8")
        (skill_dir / "docs").mkdir()
        (skill_dir / "docs" / "design.md").write_text("source-only design\n", encoding="utf-8")

        hook_scripts = self.root / "catalog" / "hooks" / "bento" / "codex" / "scripts"
        (hook_scripts / "permission-request_test.py").write_text("assert False\n", encoding="utf-8")
        (self.root / "catalog" / "hooks" / "bento" / "codex" / "README.md").write_text(
            "source-only hook notes\n",
            encoding="utf-8",
        )

        self.build_repo()

        for platform in ("claude", "codex"):
            generated_skill = self.root / "plugins" / platform / "bento" / "skills" / "closure"
            self.assertFalse((generated_skill / "tests").exists())
            self.assertFalse((generated_skill / "scripts" / "closure_test.py").exists())
            self.assertFalse((generated_skill / "README.md").exists())
            self.assertFalse((generated_skill / "docs").exists())

        codex_hooks = self.root / "plugins" / "codex" / "bento" / "hooks"
        self.assertFalse((codex_hooks / "scripts" / "permission-request_test.py").exists())
        self.assertFalse((codex_hooks / "README.md").exists())

    def test_invalid_platform_in_sidecar_raises(self) -> None:
        packaging = self.root / "catalog" / "skills" / "closure" / "packaging.json"
        packaging.write_text(json.dumps({"platforms": ["klingon"]}), encoding="utf-8")

        with self.assertRaises(SystemExit):
            self.build_repo()

    def test_build_repo_copies_red_green_tdd_guidance_into_generated_skills(self) -> None:
        self.build_repo()

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

    def test_launch_work_guidance_does_not_reference_missing_progress_log_helper(self) -> None:
        self.build_repo()

        launch_work_paths = [
            self.root / "catalog" / "skills" / "launch-work" / "SKILL.md",
            self.root / "plugins" / "claude" / "bento" / "skills" / "launch-work" / "SKILL.md",
            self.root / "plugins" / "codex" / "bento" / "skills" / "launch-work" / "SKILL.md",
            self.root
            / "plugins"
            / "claude"
            / "bento"
            / "skills"
            / "launch-work"
            / "references"
            / "project-hook-skills.md",
            self.root
            / "plugins"
            / "codex"
            / "bento"
            / "skills"
            / "launch-work"
            / "references"
            / "project-hook-skills.md",
        ]

        for path in launch_work_paths:
            self.assertTrue(path.exists(), path)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("launch-work-log.py", text, path)
            self.assertNotIn("progress log", text.lower(), path)

    def test_land_work_guidance_does_not_reference_removed_log_cleanup(self) -> None:
        self.build_repo()

        land_work_paths = [
            self.root / "catalog" / "skills" / "land-work" / "SKILL.md",
            self.root / "plugins" / "claude" / "bento" / "skills" / "land-work" / "SKILL.md",
            self.root / "plugins" / "codex" / "bento" / "skills" / "land-work" / "SKILL.md",
        ]

        for path in land_work_paths:
            self.assertTrue(path.exists(), path)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("land-work-clean-log.py", text, path)
            self.assertNotIn("$GIT_DIR/launch-work/log.md", text, path)

    def test_land_work_guidance_requires_preview_worktree_cleanup(self) -> None:
        self.build_repo()

        land_work_paths = [
            self.root / "catalog" / "skills" / "land-work" / "SKILL.md",
            self.root / "plugins" / "claude" / "bento" / "skills" / "land-work" / "SKILL.md",
            self.root / "plugins" / "codex" / "bento" / "skills" / "land-work" / "SKILL.md",
        ]

        for path in land_work_paths:
            self.assertTrue(path.exists(), path)
            normalized = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
            # Mandatory, every-exit-path cleanup of the preview worktree so
            # /tmp/land-work-preview-* dirs do not accumulate (bento-gd2).
            self.assertIn("--cleanup --preview-dir", normalized, path)
            self.assertIn("on every exit path", normalized, path)
            self.assertIn("/tmp/land-work-preview-*", normalized, path)

    def test_workflow_hook_contract_is_documented_without_tool_specific_names(self) -> None:
        self.build_repo()

        skills_dir = self.root / "plugins" / "claude" / "bento" / "skills"
        contract = skills_dir / "launch-work" / "references" / "project-hook-scripts.md"
        self.assertTrue(contract.exists())

        launch_text = (skills_dir / "launch-work" / "SKILL.md").read_text(encoding="utf-8")
        land_text = (skills_dir / "land-work" / "SKILL.md").read_text(encoding="utf-8")
        contract_text = contract.read_text(encoding="utf-8")
        combined_text = "\n".join([launch_text, land_text, contract_text])
        normalized_text = re.sub(r"\s+", " ", combined_text)

        self.assertIn("Project Hook Script Contract", contract_text)
        self.assertIn("agent-plugins/bento/bento/", contract_text)
        self.assertIn("<root>/<skill>/hook-scripts/<position>/", contract_text)
        self.assertIn("BENTO_HOOK_REQUIRES_HUMAN", contract_text)
        self.assertIn("EX_TEMPFAIL", contract_text)
        self.assertIn("Run the **`pre`** hook scripts after worktree verification and before dependency installation", normalized_text)
        self.assertIn("Run the **`pre`** hook scripts before creating or verifying the merge preview, rebasing, or merging", normalized_text)
        for forbidden in ("bugshot", "vizdiff", "playwright"):
            self.assertNotIn(forbidden, combined_text.lower())

    def test_build_repo_copies_land_work_codex_execution_guidance(self) -> None:
        self.build_repo()

        skill_text = (
            self.root / "plugins" / "codex" / "bento" / "skills" / "land-work" / "SKILL.md"
        ).read_text(encoding="utf-8")
        normalized_skill_text = re.sub(r"\s+", " ", skill_text)

        self.assertIn("Do not search the whole plugin cache", normalized_skill_text)
        self.assertIn("For Codex, avoid shell pipelines for discovery", normalized_skill_text)
        self.assertIn("git worktree list --porcelain", normalized_skill_text)

    def test_issue_completeness_precheck_is_packaged_with_tracker_flows(self) -> None:
        self.build_repo()

        for platform in ("claude", "codex"):
            for plugin in ("bento", "trackers"):
                skill_path = (
                    self.root
                    / "plugins"
                    / platform
                    / plugin
                    / "skills"
                    / "issue-readiness-check"
                    / "SKILL.md"
                )
                self.assertTrue(skill_path.exists(), skill_path)
                skill_text = skill_path.read_text(encoding="utf-8")
                self.assertIn("Hard trigger before creating, filing, drafting", skill_text)
                self.assertIn("The fresh reviewer is a required part of this precheck", skill_text)
                self.assertIn("Do not treat \"no subagent delegation was requested\" as a valid fallback reason", skill_text)
                self.assertIn("Run the lead-agent recovery loop before any filing path", skill_text)
                self.assertIn("Do not file normal ready work while reviewer-flagged ambiguities still", skill_text)

    def test_tracker_flows_delegate_filing_precheck_to_shared_skill(self) -> None:
        self.build_repo()

        for skill_name in ("beads-issue-flow", "github-issue-flow"):
            source_text = (
                self.root / "catalog" / "skills" / skill_name / "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertIn("issue-readiness-check", source_text)
            self.assertIn("## Filing New Issues", source_text)
            self.assertNotIn("## Pre-Filing Readiness Check", source_text)
            self.assertNotIn("Use a blank-slate subagent as reviewer", source_text)

    def test_bugshot_not_in_bento_external_skills(self) -> None:
        module = load_build_plugins_module()
        bento_skills = module.EXTERNAL_SKILLS.get("bento", [])
        bugshot = next((e for e in bento_skills if e["name"] == "bugshot"), None)
        self.assertIsNone(bugshot, "bugshot must not be bundled as an external skill of bento")

    def test_bugshot_in_external_plugins(self) -> None:
        module = load_build_plugins_module()
        bugshot = next((e for e in module.EXTERNAL_PLUGINS if e["name"] == "bugshot"), None)
        self.assertIsNotNone(bugshot, "bugshot should be registered in EXTERNAL_PLUGINS")
        self.assertEqual(bugshot["repo"], "ketang/bugshot")

    def test_storystore_in_external_plugins(self) -> None:
        module = load_build_plugins_module()
        storystore = next((e for e in module.EXTERNAL_PLUGINS if e["name"] == "storystore"), None)
        self.assertIsNotNone(storystore, "storystore should be registered in EXTERNAL_PLUGINS")
        self.assertEqual(storystore["repo"], "ketang/storystore")

    def test_bugshot_appears_in_claude_marketplace_as_external(self) -> None:
        self.build_repo()
        marketplace = json.loads(
            (self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        bugshot = next((p for p in marketplace["plugins"] if p["name"] == "bugshot"), None)
        self.assertIsNotNone(bugshot, "bugshot should appear in the claude marketplace")
        self.assertNotIn("version", bugshot, "external plugin entry must not carry a version field")
        self.assertIn("source", bugshot)
        self.assertEqual(bugshot["source"]["source"], "github")
        self.assertEqual(bugshot["source"]["repo"], "ketang/bugshot")

    def test_storystore_appears_in_claude_marketplace_as_external(self) -> None:
        self.build_repo()
        marketplace = json.loads(
            (self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        storystore = next((p for p in marketplace["plugins"] if p["name"] == "storystore"), None)
        self.assertIsNotNone(storystore, "storystore should appear in the claude marketplace")
        self.assertNotIn("version", storystore, "external plugin entry must not carry a version field")
        self.assertIn("source", storystore)
        self.assertEqual(storystore["source"]["source"], "github")
        self.assertEqual(storystore["source"]["repo"], "ketang/storystore")

    def test_bugshot_not_bundled_in_bento_plugin(self) -> None:
        self.build_repo()
        for platform in ("claude", "codex"):
            bento_bugshot = self.root / "plugins" / platform / "bento" / "skills" / "bugshot"
            self.assertFalse(
                bento_bugshot.exists(),
                f"bugshot must not be bundled inside bento for {platform}",
            )

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
        self.build_repo()

        for platform in ("claude", "codex"):
            self.assertFalse((self.root / "plugins" / platform / "bugshot").exists())

    def test_build_repo_prunes_stale_generated_plugin_directories(self) -> None:
        stale_dir = self.root / "plugins" / "claude" / "obsolete-pack"
        stale_dir.mkdir(parents=True)
        (stale_dir / "orphan.txt").write_text("stale\n", encoding="utf-8")

        self.build_repo()

        self.assertFalse(stale_dir.exists())

    def test_build_repo_includes_dev_skill_in_claude_bento_plugin(self) -> None:
        self.build_repo()
        dev_skill_md = (
            self.root / "plugins" / "claude" / "bento" / "skills" / "dev-skill" / "SKILL.md"
        )
        self.assertTrue(dev_skill_md.exists(), "dev-skill SKILL.md must be present in claude bento plugin")
        self.assertFalse(
            (self.root / "plugins" / "claude" / "bento" / "skills" / "dev-skill" / "packaging.json").exists(),
            "packaging.json must not be copied into the output skill directory",
        )

    def test_dev_skill_is_excluded_from_codex_bento_plugin(self) -> None:
        self.build_repo()
        codex_path = self.root / "plugins" / "codex" / "bento" / "skills" / "dev-skill"
        self.assertFalse(codex_path.exists(), "dev-skill must not appear in codex bento plugin")

    def test_check_mode_passes_when_committed_tree_matches_fresh_build(self) -> None:
        with self.maybe_skip_assets(enabled=False):
            self.module.build_repo(run_verification=False)
            self.assertEqual(self.module.check_repo(), 0)

    def test_check_mode_detects_hand_edited_generated_file(self) -> None:
        with self.maybe_skip_assets(enabled=False):
            self.module.build_repo(run_verification=False)
            target = next((self.root / "plugins").rglob("SKILL.md"))
            target.write_text(
                target.read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8"
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = self.module.check_repo()
        self.assertEqual(rc, 1)
        self.assertIn("out of date", stderr.getvalue())
        self.assertIn(target.name, stderr.getvalue())

    def test_check_mode_detects_unexpected_committed_file(self) -> None:
        with self.maybe_skip_assets(enabled=False):
            self.module.build_repo(run_verification=False)
            stray = self.root / "plugins" / "claude" / "bento" / "stray.txt"
            stray.write_text("not generated\n", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = self.module.check_repo()
        self.assertEqual(rc, 1)
        self.assertIn("unexpected hand-added", stderr.getvalue())
        self.assertIn("stray.txt", stderr.getvalue())


class BuildPluginsCheckCLITest(unittest.TestCase):
    """End-to-end: the committed plugins/ tree in this repo must already match a
    fresh build, enforcing the no-hand-edit invariant on every test run."""

    def test_committed_plugins_match_fresh_build(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            "scripts/build-plugins --check reported drift between the committed "
            "plugins/ tree and a fresh build of catalog/. Run scripts/build-plugins "
            f"to regenerate.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
