"""Doc-claims-vs-filesystem drift guard (bento-0p1).

Two refactors (bento-xzf, bento-bpi) left user-facing docs asserting a stale
world for months: a deleted `.agents/plugins/marketplace.json` documented as a
generated repo artifact, and an old flat `plugins/<plugin>/` layout. Once the
docs were corrected, nothing pinned them, so they could silently drift again.

This module pins a small, explicit set of the highest-drift documentation
claims. Each claim is re-derived from ground truth (the filesystem or a
generated manifest) and compared against what the docs currently say, so the
test fails the moment a doc regresses rather than months later. Keep the claim
list small and specific: the point is to guard the facts that actually drift,
not to mirror the docs (which would make the test its own drift source).
"""

import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Live, user-facing docs the forbidden-strings tripwire scans. Deliberately
# excludes docs/specs/ (historical design records may quote the old world by
# design) and git history.
LIVE_DOCS = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "DESIGN.md",
    "INSTALL.md",
    "hooks/README.md",
    "docs/installing-plugins.md",
    "docs/extensions.md",
    ".claude/skills/version-bump.md",
]


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """Return the body of the markdown section named `heading` (any level).

    The body runs from the heading line to the next heading of the same or
    higher level, or end of file.
    """
    lines = text.splitlines()
    start = None
    level = None
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m and m.group(2).strip() == heading:
            start = i + 1
            level = len(m.group(1))
            break
    if start is None:
        raise AssertionError(f"heading not found: {heading!r}")
    end = len(lines)
    for j in range(start, len(lines)):
        m = re.match(r"^(#{1,6})\s+", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def backticked(text: str) -> list[str]:
    """All single-backtick-quoted spans, in order."""
    return re.findall(r"`([^`]+)`", text)


class ThinkAboutRepoPathsExist(unittest.TestCase):
    """(a) Every path bullet in AGENTS.md "How to think about the repo" exists."""

    def test_path_bullets_resolve_on_disk(self) -> None:
        body = section(read("AGENTS.md"), "How to think about the repo")
        # A path-bearing token names a filesystem path: it contains a slash
        # AND its first segment matches an actual top-level repo entry. This
        # excludes non-path slash notation (e.g. "create/update", "true/false")
        # that would otherwise misfire as a "nonexistent path".
        candidates = [tok for tok in backticked(body) if "/" in tok]
        top_level = {p.name for p in REPO_ROOT.iterdir()}
        paths = [tok for tok in candidates if tok.split("/", 1)[0] in top_level]
        self.assertTrue(paths, "no path bullets extracted; section shape changed")
        missing = [p for p in paths if not (REPO_ROOT / p.rstrip("/")).exists()]
        self.assertEqual(
            missing,
            [],
            f"AGENTS.md 'How to think about the repo' names nonexistent paths: {missing}",
        )


class InstallDocPluginListMatchesManifest(unittest.TestCase):
    """(b) Plugin names in installing-plugins.md == the marketplace plugin set."""

    def test_step2_list_equals_marketplace(self) -> None:
        manifest = json.loads(read(".claude-plugin/marketplace.json"))
        manifest_names = {p["name"] for p in manifest["plugins"]}

        body = section(read("docs/installing-plugins.md"), "Step 2: Choose a plugin")
        # Each plugin bullet leads with a backticked name: "- `bento` for ...".
        doc_names = set()
        for line in body.splitlines():
            m = re.match(r"^-\s+`([a-z0-9-]+)`", line)
            if m:
                doc_names.add(m.group(1))
        self.assertTrue(doc_names, "no plugin bullets extracted; section shape changed")
        self.assertEqual(
            doc_names,
            manifest_names,
            "installing-plugins.md plugin list disagrees with "
            ".claude-plugin/marketplace.json "
            f"(doc-only={sorted(doc_names - manifest_names)}, "
            f"manifest-only={sorted(manifest_names - doc_names)})",
        )


class ReadmeLayoutMatchesPluginsTree(unittest.TestCase):
    """(c) README's plugins-layout snippet matches the actual plugins/ tree."""

    def test_readme_documents_platform_first_layout(self) -> None:
        body = section(read("README.md"), "Generated plugin format")
        # Doc side: the snippet must describe the platform-first two-level tree
        # and must not reprint the old flat `plugins/<plugin-name>/` layout.
        for needle in ("plugins/", "claude/", "codex/", "plugin-names.txt"):
            self.assertIn(needle, body, f"README layout snippet missing {needle!r}")
        self.assertNotIn(
            "plugins/<plugin-name>/\n",
            body,
            "README layout snippet reprints the old flat plugins/<plugin-name>/ tree",
        )

    def test_plugins_tree_is_platform_first_on_disk(self) -> None:
        plugins = REPO_ROOT / "plugins"
        claude = plugins / "claude"
        codex = plugins / "codex"
        self.assertTrue(claude.is_dir(), "plugins/claude/ missing")
        self.assertTrue(codex.is_dir(), "plugins/codex/ missing")
        self.assertTrue(
            (codex / "plugin-names.txt").is_file(),
            "plugins/codex/plugin-names.txt missing",
        )
        # Structural invariants the README snippet promises for each plugin.
        # skills/ and hooks/ are both documented; the snippet marks hooks/ as
        # "present only when the plugin declares hooks", so a hook-only plugin
        # (hygiene, session-id) has hooks/ and no skills/. Require the manifest
        # plus at least one of skills/ or hooks/.
        for d in sorted(p for p in claude.iterdir() if p.is_dir()):
            self.assertTrue(
                (d / ".claude-plugin" / "plugin.json").is_file(),
                f"{d.name}: missing .claude-plugin/plugin.json",
            )
            self.assertTrue(
                (d / "skills").is_dir() or (d / "hooks").is_dir(),
                f"{d.name}: has neither skills/ nor hooks/",
            )
        for d in sorted(p for p in codex.iterdir() if p.is_dir()):
            self.assertTrue(
                (d / ".codex-plugin" / "plugin.json").is_file(),
                f"{d.name}: missing .codex-plugin/plugin.json",
            )
            self.assertTrue(
                (d / "skills").is_dir() or (d / "hooks").is_dir(),
                f"{d.name}: has neither skills/ nor hooks/",
            )


class VersionBumpGitAddPathsExist(unittest.TestCase):
    """(d) Every pathspec in version-bump.md's documented `git add` line exists."""

    def test_documented_git_add_pathspecs_resolve(self) -> None:
        # Scoped to Step 6 so an earlier illustrative `git add` example
        # elsewhere in the doc can't silently become the one under test.
        text = section(
            read(".claude/skills/version-bump.md"), "Step 6 — Act on the classification"
        )
        m = re.search(r"^\s*git add (.+)$", text, re.MULTILINE)
        self.assertIsNotNone(m, "no `git add` line found in version-bump.md Step 6")
        pathspecs = m.group(1).split()
        self.assertTrue(pathspecs, "git add line has no pathspecs")
        missing = [p for p in pathspecs if not (REPO_ROOT / p.rstrip("/")).exists()]
        self.assertEqual(
            missing,
            [],
            f"version-bump.md `git add` line names nonexistent pathspecs: {missing}",
        )


class ForbiddenStalePhrasesAbsent(unittest.TestCase):
    """(e) Purged stale-world claims must not reappear in any live doc."""

    # Each string is an exact phrase removed by bento-xzf / bento-bpi. They
    # encode a claim that is now false: a deleted file documented as a
    # generated repo artifact, a build step that never produced it, a false
    # manual-hook-wiring instruction, or the old flat plugins/ layout. The bare
    # path `.agents/plugins/marketplace.json` is intentionally NOT forbidden --
    # the Codex installer legitimately writes it at install time.
    FORBIDDEN = [
        "`.agents/plugins/marketplace.json` contains generated",
        "`.agents/plugins/marketplace.json` because it is generated",
        "rebuilds the root `.agents/plugins/marketplace.json",
        "wired manually in `~/.claude/settings.json",
        "plugins/<plugin-name>/.codex-plugin",
        "plugins/<plugin-name>/.claude-plugin",
    ]

    def test_no_live_doc_contains_a_forbidden_phrase(self) -> None:
        hits = []
        for rel in LIVE_DOCS:
            text = read(rel)
            for phrase in self.FORBIDDEN:
                if phrase in text:
                    hits.append(f"{rel}: {phrase!r}")
        self.assertEqual(hits, [], "stale-world phrases reappeared:\n" + "\n".join(hits))


class BeadsCodexBlockStaysMinimal(unittest.TestCase):
    """Tripwire: keep the `bd setup codex` block in AGENTS.md minimal.

    Operator note on bento-0p1: a re-run of `bd setup codex` regenerates the
    full ~105-word Beads block between the BEGIN/END markers, which then rides
    every session's context silently. This tripwire fails such a regeneration.

    Currently SKIPPED: the minimization it guards (bento-jdg) has not landed, so
    the block is still the full generated version (~120 words). Remove the skip
    when bento-jdg lands and the block is minimized under the threshold.
    """

    MAX_WORDS = 40

    def _block_words(self) -> int:
        text = read("AGENTS.md")
        m = re.search(
            r"<!-- BEGIN BEADS CODEX SETUP.*?-->(.*?)<!-- END BEADS CODEX SETUP -->",
            text,
            re.S,
        )
        assert m, "BEADS CODEX SETUP markers not found in AGENTS.md"
        return len(m.group(1).split())

    @unittest.skip("Activate when bento-jdg minimizes the Beads block; see bento-0p1")
    def test_block_under_word_budget(self) -> None:
        self.assertLessEqual(
            self._block_words(),
            self.MAX_WORDS,
            "AGENTS.md Beads codex block exceeds the word budget -- likely "
            "regenerated by `bd setup codex`; re-minimize it (see bento-jdg).",
        )


if __name__ == "__main__":
    unittest.main()
