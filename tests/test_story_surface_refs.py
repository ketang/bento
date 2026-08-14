"""Guard the storystore surface-ref contract for docs/stories/.

storystore's audit resolves ``Evidence.Surface`` refs against an inventory it
extracts from the repo. Its parseable prefixes are cli, route, bin, export(s),
test, heading, doc, and schema; anything else is reported as a
``surface-missing`` finding, and any finding on a story blocks stories-update's
guarded-edit workflow for that story.

Bento's user-facing surfaces are agent skills, which no storystore extractor
recognizes, so these stories omit the optional Surface subsection and carry the
skill identity in the slug, title, and Evidence.Docs paths instead. See
docs/stories/README.md for the rationale. This test keeps a future story from
reintroducing an unresolvable ref and re-jamming the corpus.
"""

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STORIES_DIR = REPO_ROOT / "docs" / "stories"
NON_STORY_FILES = {"README.md", "INDEX.md", "drift-todo.md"}

# Prefixes storystore's _validate_surface_ref accepts. Refs under cli, route,
# bin, and export(s) are additionally matched against the extracted inventory;
# bento extracts no such surfaces, so they would still be reported missing.
INVENTORY_MATCHED_PREFIXES = frozenset({"cli", "route", "bin", "export", "exports"})
UNVALIDATED_PREFIXES = frozenset({"test", "heading", "doc", "schema"})

_SURFACE_HEADING_RE = re.compile(r"^###\s+Surface\s*$")
_SUBSECTION_RE = re.compile(r"^#")
_BULLET_RE = re.compile(r"^\s*[-*]\s+`?(?P<ref>[^`]+)`?\s*$")
_PREFIX_RE = re.compile(r"^(?P<prefix>[a-zA-Z][a-zA-Z0-9_-]*)\s*:")


def story_files() -> list[Path]:
    return sorted(p for p in STORIES_DIR.glob("*.md") if p.name not in NON_STORY_FILES)


def surface_refs(path: Path) -> list[str]:
    refs: list[str] = []
    in_surface = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if _SURFACE_HEADING_RE.match(line):
            in_surface = True
            continue
        if in_surface and _SUBSECTION_RE.match(line):
            break
        if in_surface:
            match = _BULLET_RE.match(line)
            if match:
                refs.append(match.group("ref").strip())
    return refs


class StorySurfaceRefTest(unittest.TestCase):
    def test_stories_exist(self) -> None:
        self.assertTrue(story_files(), f"no stories found under {STORIES_DIR}")

    def test_surface_refs_resolve_under_storystore_audit(self) -> None:
        offenders: list[str] = []
        for path in story_files():
            for ref in surface_refs(path):
                match = _PREFIX_RE.match(ref)
                prefix = match.group("prefix").lower() if match else None
                if prefix in UNVALIDATED_PREFIXES:
                    continue
                if prefix in INVENTORY_MATCHED_PREFIXES:
                    offenders.append(
                        f"{path.name}: `{ref}` is parseable but bento extracts no "
                        f"{prefix} surfaces, so audit reports surface-missing"
                    )
                else:
                    offenders.append(
                        f"{path.name}: `{ref}` uses an unparseable surface prefix"
                    )
        self.assertEqual(
            [],
            offenders,
            "storystore's stories-audit would report surface-missing findings, "
            "which block stories-update on those stories. Omit the Surface "
            "subsection and record the skill in Evidence.Docs instead; see "
            "docs/stories/README.md.\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
