import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "catalog/skills/compress-docs/scripts/compress-discover.py"


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd, check=check)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class CompressDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Compress Docs Test")
        git(self.repo, "config", "user.email", "compress@example.com")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_helper(self, env_overrides: dict[str, str] | None = None) -> dict:
        import os
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        result = subprocess.run(
            [str(SCRIPT)],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return json.loads(result.stdout)

    def test_helper_runs_and_emits_json(self) -> None:
        data = self.run_helper()
        self.assertIsInstance(data, dict)

    def test_tier_1_includes_top_level_agent_docs_and_nested_claude_md(self) -> None:
        write(self.repo / "CLAUDE.md", "# project claude\n")
        write(self.repo / "AGENTS.md", "# agents\n")
        write(self.repo / "GEMINI.md", "# gemini\n")
        write(self.repo / "subdir/CLAUDE.md", "# nested\n")
        write(self.repo / "unrelated.md", "# not in tier 1\n")

        data = self.run_helper()

        tier_1_paths = sorted(
            entry["path"] for entry in data["scope"] if entry["tier"] == 1
        )
        self.assertEqual(
            tier_1_paths,
            sorted(
                str(self.repo / name)
                for name in ["AGENTS.md", "CLAUDE.md", "GEMINI.md", "subdir/CLAUDE.md"]
            ),
        )
        for entry in data["scope"]:
            if entry["tier"] == 1:
                self.assertIn("bytes", entry)
                self.assertIn("lines", entry)
                self.assertIn("tokens_char4", entry)

    def test_tier_2_follows_markdown_links_and_backticked_paths_up_to_depth_3(self) -> None:
        write(
            self.repo / "CLAUDE.md",
            "See [guide](docs/guide.md) and `docs/reference.md` for details.\n",
        )
        write(self.repo / "docs/guide.md", "Linked from root. See [deep](deep/a.md).\n")
        write(self.repo / "docs/reference.md", "Backticked from root.\n")
        write(self.repo / "docs/deep/a.md", "Depth 2. See [next](b.md).\n")
        write(self.repo / "docs/deep/b.md", "Depth 3. See [too-far](c.md).\n")
        write(self.repo / "docs/deep/c.md", "Depth 4 — excluded.\n")
        write(self.repo / "docs/unreferenced.md", "Not linked from anywhere.\n")

        data = self.run_helper()

        tier_2_paths = sorted(
            entry["path"] for entry in data["scope"] if entry["tier"] == 2
        )
        self.assertEqual(
            tier_2_paths,
            sorted(
                str(self.repo / rel)
                for rel in [
                    "docs/guide.md",
                    "docs/reference.md",
                    "docs/deep/a.md",
                    "docs/deep/b.md",
                ]
            ),
        )

    def test_tier_2_excludes_references_outside_repo(self) -> None:
        write(
            self.repo / "CLAUDE.md",
            "See `/etc/passwd` and [external](../outside.md).\n",
        )
        data = self.run_helper()
        tier_2_paths = [entry["path"] for entry in data["scope"] if entry["tier"] == 2]
        self.assertEqual(tier_2_paths, [])

    def test_tier_3_uses_user_claude_md_from_home(self) -> None:
        fake_home = Path(self.temp_dir.name) / "home"
        (fake_home / ".claude").mkdir(parents=True)
        write(fake_home / ".claude/CLAUDE.md", "# global\n")

        data = self.run_helper(env_overrides={"HOME": str(fake_home)})

        tier_3_paths = [entry["path"] for entry in data["scope"] if entry["tier"] == 3]
        self.assertEqual(tier_3_paths, [str(fake_home / ".claude/CLAUDE.md")])

    def test_tier_4_reads_memory_files_under_project_slug(self) -> None:
        fake_home = Path(self.temp_dir.name) / "home"
        slug = str(self.repo).replace("/", "-").lstrip("-")
        memory_dir = fake_home / ".claude/projects" / slug / "memory"
        memory_dir.mkdir(parents=True)
        write(memory_dir / "MEMORY.md", "# memory index\n")
        write(memory_dir / "user_profile.md", "# user\n")

        data = self.run_helper(env_overrides={"HOME": str(fake_home)})

        tier_4_paths = sorted(
            entry["path"] for entry in data["scope"] if entry["tier"] == 4
        )
        self.assertEqual(
            tier_4_paths,
            sorted(
                str(memory_dir / name) for name in ["MEMORY.md", "user_profile.md"]
            ),
        )

    def test_missing_tier_3_and_tier_4_does_not_crash(self) -> None:
        fake_home = Path(self.temp_dir.name) / "empty_home"
        fake_home.mkdir()
        data = self.run_helper(env_overrides={"HOME": str(fake_home)})
        tiers = {entry["tier"] for entry in data["scope"]}
        self.assertNotIn(3, tiers)
        self.assertNotIn(4, tiers)

    def test_dead_references_flags_missing_paths_and_commands(self) -> None:
        write(
            self.repo / "CLAUDE.md",
            (
                "Run `scripts/old-tool.sh` to verify.\n"
                "Also `scripts/build-plugins` is fine.\n"
                "Use `definitely-not-a-command` for deploys.\n"
                "See [missing](docs/missing.md) and [present](docs/present.md).\n"
            ),
        )
        write(self.repo / "scripts/build-plugins", "#!/bin/sh\n")
        (self.repo / "scripts/build-plugins").chmod(0o755)
        write(self.repo / "docs/present.md", "I exist.\n")

        data = self.run_helper()

        missing_refs = {
            entry["reference"]
            for entry in data["dead_references"]
            if entry["resolution"] == "missing"
        }
        self.assertIn("scripts/old-tool.sh", missing_refs)
        self.assertIn("docs/missing.md", missing_refs)
        self.assertIn("definitely-not-a-command", missing_refs)
        self.assertNotIn("scripts/build-plugins", missing_refs)
        self.assertNotIn("docs/present.md", missing_refs)
        for entry in data["dead_references"]:
            self.assertIn("source", entry)
            self.assertIn("line", entry)
            self.assertIn("kind", entry)

    def test_duplicate_blocks_flag_identical_paragraphs_across_files(self) -> None:
        shared = (
            "## Plan Mode Default\n"
            "Enter plan mode for any non-trivial task.\n"
            "Re-plan if something goes sideways.\n"
        )
        write(self.repo / "CLAUDE.md", shared + "\nUnique to CLAUDE.md.\n")
        write(self.repo / "AGENTS.md", "Unique to AGENTS.md.\n\n" + shared)

        data = self.run_helper()

        self.assertEqual(len(data["duplicate_blocks"]), 1)
        block = data["duplicate_blocks"][0]
        occurrence_paths = sorted(occ["path"] for occ in block["occurrences"])
        self.assertEqual(
            occurrence_paths,
            sorted(str(self.repo / name) for name in ["AGENTS.md", "CLAUDE.md"]),
        )

    def test_duplicate_blocks_ignore_short_paragraphs(self) -> None:
        short_block = "short.\nshort.\n"
        write(self.repo / "CLAUDE.md", short_block + "\nother\n")
        write(self.repo / "AGENTS.md", short_block + "\nstuff\n")

        data = self.run_helper()
        self.assertEqual(data["duplicate_blocks"], [])
