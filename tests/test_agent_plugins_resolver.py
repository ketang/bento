import tempfile
import unittest
from pathlib import Path

from tests.script_test_utils import load_module, write


REPO_ROOT = Path(__file__).resolve().parents[1]
RESOLVER = load_module(
    REPO_ROOT / "docs" / "specs" / "reference" / "agent_plugins_resolver.py"
)


class AgentPluginsResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_home_config_root_uses_platform_defaults(self) -> None:
        home = self.tmp_path / "home"
        xdg = self.tmp_path / "xdg"

        self.assertEqual(
            RESOLVER.home_config_root(env={}, platform="linux", home=home),
            home / ".config",
        )
        self.assertEqual(
            RESOLVER.home_config_root(
                env={"XDG_CONFIG_HOME": str(xdg)}, platform="linux", home=home
            ),
            xdg,
        )
        self.assertEqual(
            RESOLVER.home_config_root(env={}, platform="darwin", home=home),
            home / "Library" / "Application Support",
        )
        self.assertEqual(
            RESOLVER.home_config_root(
                env={"XDG_CONFIG_HOME": str(xdg)}, platform="darwin", home=home
            ),
            xdg,
        )
        self.assertEqual(
            RESOLVER.home_config_root(
                env={"APPDATA": "C:/Users/K/AppData/Roaming"},
                platform="win32",
                home=home,
            ),
            Path("C:/Users/K/AppData/Roaming"),
        )
        self.assertEqual(
            RESOLVER.home_config_root(
                env={"USERPROFILE": "C:/Users/K"}, platform="win32", home=home
            ),
            Path("C:/Users/K") / "AppData" / "Roaming",
        )

    def test_repo_scope_overrides_home_and_bundled(self) -> None:
        repo = self.tmp_path / "repo"
        xdg = self.tmp_path / "xdg"
        bundled = self.tmp_path / "bundled" / "rules.md"
        repo_file = repo / ".agent-plugins" / "example" / "widgets" / "rules.md"
        home_file = xdg / "agent-plugins" / "example" / "widgets" / "rules.md"
        write(repo_file, "repo\n")
        write(home_file, "home\n")
        write(bundled, "bundled\n")

        result = RESOLVER.resolve_customization_file(
            marketplace="example",
            plugin="widgets",
            rel_path="rules.md",
            repo_root=repo,
            bundled_default_path=bundled,
            env={"XDG_CONFIG_HOME": str(xdg)},
            platform="linux",
        )

        self.assertEqual(result.source, "repo")
        self.assertEqual(result.path, repo_file)

    def test_home_scope_overrides_bundled_when_repo_file_is_missing(self) -> None:
        repo = self.tmp_path / "repo"
        xdg = self.tmp_path / "xdg"
        bundled = self.tmp_path / "bundled" / "rules.md"
        home_file = xdg / "agent-plugins" / "example" / "widgets" / "rules.md"
        write(home_file, "home\n")
        write(bundled, "bundled\n")

        result = RESOLVER.resolve_customization_file(
            marketplace="example",
            plugin="widgets",
            rel_path="rules.md",
            repo_root=repo,
            bundled_default_path=bundled,
            env={"XDG_CONFIG_HOME": str(xdg)},
            platform="linux",
        )

        self.assertEqual(result.source, "home")
        self.assertEqual(result.path, home_file)

    def test_bundled_default_is_used_last_and_missing_files_return_none(self) -> None:
        xdg = self.tmp_path / "xdg"
        bundled = self.tmp_path / "bundled" / "rules.md"
        write(bundled, "bundled\n")

        result = RESOLVER.resolve_customization_file(
            marketplace="example",
            plugin="widgets",
            rel_path="rules.md",
            bundled_default_path=bundled,
            env={"XDG_CONFIG_HOME": str(xdg)},
            platform="linux",
        )
        self.assertEqual(result.source, "bundled")
        self.assertEqual(result.path, bundled)

        missing = RESOLVER.resolve_customization_file(
            marketplace="example",
            plugin="widgets",
            rel_path="missing.md",
            env={"XDG_CONFIG_HOME": str(xdg)},
            platform="linux",
        )
        self.assertIsNone(missing)

    def test_lookup_is_per_file(self) -> None:
        xdg = self.tmp_path / "xdg"
        bundled_a = self.tmp_path / "bundled" / "a.md"
        bundled_b = self.tmp_path / "bundled" / "b.md"
        home_a = xdg / "agent-plugins" / "example" / "widgets" / "a.md"
        write(home_a, "home a\n")
        write(bundled_a, "bundled a\n")
        write(bundled_b, "bundled b\n")

        result_a = RESOLVER.resolve_customization_file(
            marketplace="example",
            plugin="widgets",
            rel_path="a.md",
            bundled_default_path=bundled_a,
            env={"XDG_CONFIG_HOME": str(xdg)},
            platform="linux",
        )
        result_b = RESOLVER.resolve_customization_file(
            marketplace="example",
            plugin="widgets",
            rel_path="b.md",
            bundled_default_path=bundled_b,
            env={"XDG_CONFIG_HOME": str(xdg)},
            platform="linux",
        )

        self.assertEqual(result_a.source, "home")
        self.assertEqual(result_b.source, "bundled")

    def test_find_repo_root_accepts_git_file_or_directory(self) -> None:
        repo_with_dir = self.tmp_path / "repo-dir"
        nested_dir = repo_with_dir / "a" / "b"
        (repo_with_dir / ".git").mkdir(parents=True)
        nested_dir.mkdir(parents=True)

        repo_with_file = self.tmp_path / "repo-file"
        nested_file = repo_with_file / "a" / "b"
        nested_file.mkdir(parents=True)
        write(repo_with_file / ".git", "gitdir: ../actual\n")

        self.assertEqual(RESOLVER.find_repo_root(nested_dir), repo_with_dir)
        self.assertEqual(RESOLVER.find_repo_root(nested_file), repo_with_file)

    def test_unsafe_relative_paths_are_rejected(self) -> None:
        for rel_path in ("../secret", "/abs", r"C:\secret\file", "a/../b", "a//b"):
            with self.subTest(rel_path=rel_path):
                with self.assertRaises(ValueError):
                    RESOLVER.candidate_paths(
                        marketplace="example",
                        plugin="widgets",
                        rel_path=rel_path,
                    )

    def test_unsafe_identifier_segments_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RESOLVER.candidate_paths(
                marketplace="ex/ample",
                plugin="widgets",
                rel_path="rules.md",
            )
        with self.assertRaises(ValueError):
            RESOLVER.candidate_paths(
                marketplace="example",
                plugin="CON",
                rel_path="rules.md",
            )


if __name__ == "__main__":
    unittest.main()
