import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "install" / "_codex-installer-lib.sh"


class CodexInstallerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.main_archive = self.root / "bento.tar.gz"
        self.bugshot_archive = self.root / "bugshot.tar.gz"

        self._write_main_archive()
        self._write_bugshot_archive()
        self._write_mock_curl()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_home_install_writes_paths_relative_to_marketplace_file_and_enables_bento(self) -> None:
        install_root = self.root / "home"
        plugin_root, marketplace_path, codex_cache_root, codex_config_path, _result = self.run_installer(
            "home",
            install_root,
            enable_codex=True,
        )

        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        actual_sources = {
            entry["name"]: entry["source"]["path"]
            for entry in marketplace["plugins"]
            if entry.get("name") in {"bento", "trackers", "stacks", "bugshot"}
        }

        self.assertEqual(
            actual_sources,
            {
                "bento": "./../../plugins/bento",
                "trackers": "./../../plugins/trackers",
                "stacks": "./../../plugins/stacks",
                "bugshot": "./../../plugins/bugshot",
            },
        )
        self.assertEqual((plugin_root / "bento" / "README.txt").read_text(encoding="utf-8"), "bento\n")
        self.assertEqual((plugin_root / "bugshot" / "README.txt").read_text(encoding="utf-8"), "bugshot\n")
        bento_cache_versions = list((codex_cache_root / "bento").iterdir())
        self.assertEqual(len(bento_cache_versions), 1)
        self.assertEqual((bento_cache_versions[0] / "README.txt").read_text(encoding="utf-8"), "bento\n")
        self.assertTrue((bento_cache_versions[0] / ".codex-plugin" / "plugin.json").exists())
        self.assertFalse((codex_cache_root / "trackers").exists())
        self.assertIn('[plugins."bento@bento"]\nenabled = true', codex_config_path.read_text(encoding="utf-8"))

    def test_project_install_writes_paths_relative_to_marketplace_file(self) -> None:
        install_root = self.root / "project"
        plugin_root, marketplace_path, codex_cache_root, codex_config_path, _result = self.run_installer(
            "project",
            install_root,
        )

        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        actual_sources = {
            entry["name"]: entry["source"]["path"]
            for entry in marketplace["plugins"]
            if entry.get("name") in {"bento", "trackers", "stacks", "bugshot"}
        }

        self.assertEqual(
            actual_sources,
            {
                "bento": "./../../plugins/bento",
                "trackers": "./../../plugins/trackers",
                "stacks": "./../../plugins/stacks",
                "bugshot": "./../../plugins/bugshot",
            },
        )
        self.assertTrue((plugin_root / "trackers" / ".codex-plugin" / "plugin.json").exists())
        self.assertTrue((plugin_root / "stacks" / ".codex-plugin" / "plugin.json").exists())
        self.assertFalse(codex_cache_root.exists())
        self.assertFalse(codex_config_path.exists())

    def test_codex_config_enablement_is_idempotent(self) -> None:
        install_root = self.root / "home-idempotent"
        _plugin_root, _marketplace_path, _codex_cache_root, codex_config_path, _result = self.run_installer(
            "home",
            install_root,
            enable_codex=True,
        )

        self.run_installer("home", install_root, enable_codex=True)

        config_text = codex_config_path.read_text(encoding="utf-8")
        self.assertEqual(config_text.count('[plugins."bento@bento"]'), 1)
        self.assertEqual(config_text.count("enabled = true"), 2)

    def test_home_install_removes_legacy_unkeyed_cache_layout(self) -> None:
        install_root = self.root / "home-legacy-cache"
        legacy_cache = install_root / ".codex" / "plugins" / "cache" / "bento" / "bento"
        (legacy_cache / "skills").mkdir(parents=True, exist_ok=True)
        (legacy_cache / ".codex-plugin").mkdir(parents=True, exist_ok=True)
        (legacy_cache / "skills" / "stale.txt").write_text("stale\n", encoding="utf-8")

        _plugin_root, _marketplace_path, codex_cache_root, _codex_config_path, _result = self.run_installer(
            "home",
            install_root,
            enable_codex=True,
        )

        self.assertFalse((legacy_cache / "skills").exists())
        bento_cache_versions = list((codex_cache_root / "bento").iterdir())
        self.assertEqual(len(bento_cache_versions), 1)
        self.assertTrue((bento_cache_versions[0] / ".codex-plugin" / "plugin.json").exists())

    def run_installer(
        self,
        scope: str,
        install_root: Path,
        *,
        enable_codex: bool = False,
    ) -> tuple[Path, Path, Path, Path, subprocess.CompletedProcess[str]]:
        install_root.mkdir(parents=True, exist_ok=True)
        plugin_root = install_root / "plugins"
        marketplace_path = install_root / ".agents" / "plugins" / "marketplace.json"
        codex_cache_root = install_root / ".codex" / "plugins" / "cache" / "bento"
        codex_config_path = install_root / ".codex" / "config.toml"
        marketplace_path.parent.mkdir(parents=True, exist_ok=True)
        marketplace_path.write_text(
            json.dumps(
                {
                    "name": "existing",
                    "plugins": [
                        {
                            "name": "keep-me",
                            "source": {"source": "local", "path": "./plugins/keep-me"},
                            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                            "category": "Coding",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if enable_codex and not codex_config_path.exists():
            codex_config_path.parent.mkdir(parents=True, exist_ok=True)
            codex_config_path.write_text(
                '[plugins."github@openai-curated"]\n'
                "enabled = true\n",
                encoding="utf-8",
            )

        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env.get('PATH', '')}"
        env["MOCK_BENTO_ARCHIVE"] = str(self.main_archive)
        env["MOCK_BUGSHOT_ARCHIVE"] = str(self.bugshot_archive)
        env["BENTO_INSTALL_SCOPE"] = scope
        env["BENTO_INSTALL_ROOT"] = str(install_root)
        env["BENTO_PLUGIN_ROOT"] = str(plugin_root)
        env["BENTO_MARKETPLACE_PATH"] = str(marketplace_path)
        env["BENTO_ARCHIVE_URL"] = "https://example.invalid/bento.tar.gz"
        if enable_codex:
            env["BENTO_CODEX_PLUGIN_CACHE_ROOT"] = str(codex_cache_root)
            env["BENTO_CODEX_CONFIG_PATH"] = str(codex_config_path)
            env["BENTO_CODEX_ENABLED_PLUGIN"] = "bento"

        result = subprocess.run(
            ["bash", str(INSTALLER)],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        updated_marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        plugin_names = [entry["name"] for entry in updated_marketplace["plugins"]]
        self.assertIn("keep-me", plugin_names)
        backups = sorted(marketplace_path.parent.glob("marketplace.json.bak.*"))
        self.assertGreaterEqual(len(backups), 1)
        if enable_codex:
            config_backups = sorted(codex_config_path.parent.glob("config.toml.bak.*"))
            self.assertGreaterEqual(len(config_backups), 1)

        return plugin_root, marketplace_path, codex_cache_root, codex_config_path, result

    def _write_main_archive(self) -> None:
        source_root = self.root / "source" / "bento-main"
        plugin_defs = {
            "bento": "Coding",
            "trackers": "Productivity",
            "stacks": "Coding",
        }
        for name, category in plugin_defs.items():
            plugin_dir = source_root / "plugins" / "codex" / name
            (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
            (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"interface": {"category": category}}, indent=2) + "\n",
                encoding="utf-8",
            )
            (plugin_dir / "README.txt").write_text(f"{name}\n", encoding="utf-8")

        self._make_archive(source_root, self.main_archive)

    def _write_bugshot_archive(self) -> None:
        source_root = self.root / "source" / "bugshot-main"
        plugin_dir = source_root
        (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
        (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"interface": {"category": "Coding"}}, indent=2) + "\n",
            encoding="utf-8",
        )
        (plugin_dir / "README.txt").write_text("bugshot\n", encoding="utf-8")

        self._make_archive(source_root, self.bugshot_archive)

    def _make_archive(self, source_root: Path, archive_path: Path) -> None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(source_root, arcname=source_root.name)

    def _write_mock_curl(self) -> None:
        curl_path = self.bin_dir / "curl"
        curl_path.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                output=""
                url=""
                while [[ $# -gt 0 ]]; do
                  case "$1" in
                    -o)
                      output="$2"
                      shift 2
                      ;;
                    -fsSL|-f|-s|-S|-L)
                      shift
                      ;;
                    *)
                      url="$1"
                      shift
                      ;;
                  esac
                done

                case "$url" in
                  *ketang/bugshot*)
                    source_archive="${MOCK_BUGSHOT_ARCHIVE}"
                    ;;
                  *)
                    source_archive="${MOCK_BENTO_ARCHIVE}"
                    ;;
                esac

                if [[ -n "$output" ]]; then
                  cp "$source_archive" "$output"
                else
                  cat "$source_archive"
                fi
                """
            ),
            encoding="utf-8",
        )
        curl_path.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
