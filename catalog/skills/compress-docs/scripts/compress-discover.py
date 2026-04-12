#!/usr/bin/env python3
"""compress-docs deterministic helper. Emits JSON describing in-scope
documentation files and deterministic signals (dead references, duplicate
blocks, orphan files, token baseline).

Usage:
    compress-discover.py [--repo-root PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

CHARS_PER_TOKEN_ESTIMATE = 4
TIER_1_TOP_LEVEL_NAMES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
TIER_1_NESTED_NAME = "CLAUDE.md"
TIER_2_MAX_DEPTH = 3
MIN_DUPLICATE_BLOCK_LINES = 3


def measure_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "bytes": len(text.encode("utf-8")),
        "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        "tokens_char4": len(text) // CHARS_PER_TOKEN_ESTIMATE,
    }


def discover_tier_1(repo_root: Path) -> list[Path]:
    found: set[Path] = set()
    for name in TIER_1_TOP_LEVEL_NAMES:
        candidate = repo_root / name
        if candidate.is_file():
            found.add(candidate.resolve())
    for nested in repo_root.rglob(TIER_1_NESTED_NAME):
        if nested.resolve() in found:
            continue
        found.add(nested.resolve())
    return sorted(found)


MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BACKTICK_PATH_RE = re.compile(r"`([^`\n]+)`")


def extract_references(text: str) -> list[str]:
    refs: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        refs.append(match.group(1))
    for match in BACKTICK_PATH_RE.finditer(text):
        candidate = match.group(1).strip()
        if "/" in candidate or candidate.endswith(".md"):
            refs.append(candidate)
    return refs


def resolve_reference(ref: str, source_file: Path, repo_root: Path) -> Path | None:
    if ref.startswith(("http://", "https://", "mailto:")):
        return None
    ref_clean = ref.split("#", 1)[0].split("?", 1)[0]
    if not ref_clean:
        return None
    candidate = (source_file.parent / ref_clean).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def discover_tier_2(tier_1_paths: list[Path], repo_root: Path) -> list[Path]:
    visited: set[Path] = set(tier_1_paths)
    tier_2: set[Path] = set()
    frontier: list[tuple[Path, int]] = [(p, 0) for p in tier_1_paths]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= TIER_2_MAX_DEPTH:
            continue
        try:
            text = current.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ref in extract_references(text):
            resolved = resolve_reference(ref, current, repo_root)
            if resolved is None or resolved in visited:
                continue
            visited.add(resolved)
            tier_2.add(resolved)
            frontier.append((resolved, depth + 1))
    return sorted(tier_2)


TIER_3_USER_GLOBAL = ".claude/CLAUDE.md"
TIER_4_MEMORY_DIR = ".claude/projects"
TIER_4_MEMORY_SUBDIR = "memory"


def discover_tier_3(home: Path) -> list[Path]:
    candidate = home / TIER_3_USER_GLOBAL
    if candidate.is_file():
        return [candidate.resolve()]
    return []


def project_memory_slug(repo_root: Path) -> str:
    return str(repo_root).replace("/", "-").lstrip("-")


def discover_tier_4(home: Path, repo_root: Path) -> list[Path]:
    slug = project_memory_slug(repo_root)
    memory_dir = home / TIER_4_MEMORY_DIR / slug / TIER_4_MEMORY_SUBDIR
    if not memory_dir.is_dir():
        return []
    return sorted(p.resolve() for p in memory_dir.glob("*.md") if p.is_file())


COMMAND_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")


def classify_backtick_content(content: str) -> str:
    if "/" in content or content.endswith(".md") or content.endswith(".py"):
        return "path"
    if COMMAND_NAME_RE.match(content):
        return "command"
    return "other"


def iter_references_with_lines(text: str) -> list[tuple[int, str, str]]:
    results: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in MARKDOWN_LINK_RE.finditer(line):
            results.append((lineno, match.group(1), "path"))
        for match in BACKTICK_PATH_RE.finditer(line):
            content = match.group(1).strip()
            kind = classify_backtick_content(content)
            if kind == "other":
                continue
            results.append((lineno, content, kind))
    return results


def detect_dead_references(
    scope: list[dict], repo_root: Path
) -> list[dict]:
    dead: list[dict] = []
    for entry in scope:
        path = Path(entry["path"])
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, ref, kind in iter_references_with_lines(text):
            if ref.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolution = "present"
            if kind == "path":
                ref_clean = ref.split("#", 1)[0].split("?", 1)[0]
                if not ref_clean:
                    continue
                candidate = (path.parent / ref_clean).resolve()
                try:
                    candidate.relative_to(repo_root)
                except ValueError:
                    resolution = "external"
                else:
                    if not candidate.exists():
                        resolution = "missing"
            elif kind == "command":
                if shutil.which(ref) is None and not (repo_root / "scripts" / ref).exists():
                    resolution = "missing"
            if resolution == "missing":
                dead.append(
                    {
                        "source": str(path),
                        "line": lineno,
                        "reference": ref,
                        "kind": kind,
                        "resolution": "missing",
                    }
                )
    return dead


def normalize_paragraph(lines: list[str]) -> str:
    return "\n".join(" ".join(line.split()) for line in lines)


def iter_paragraphs(text: str) -> list[tuple[int, int, list[str]]]:
    paragraphs: list[tuple[int, int, list[str]]] = []
    current: list[str] = []
    start_line = 0
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if raw_line.strip() == "":
            if current:
                paragraphs.append((start_line, lineno - 1, current))
                current = []
            start_line = 0
        else:
            if not current:
                start_line = lineno
            current.append(raw_line)
    if current:
        paragraphs.append((start_line, start_line + len(current) - 1, current))
    return paragraphs


def detect_duplicate_blocks(scope: list[dict]) -> list[dict]:
    hash_to_occurrences: dict[str, list[dict]] = {}
    for entry in scope:
        path = Path(entry["path"])
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for start, end, lines in iter_paragraphs(text):
            if len(lines) < MIN_DUPLICATE_BLOCK_LINES:
                continue
            normalized = normalize_paragraph(lines)
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
            hash_to_occurrences.setdefault(digest, []).append(
                {"path": str(path), "start": start, "end": end}
            )
    blocks: list[dict] = []
    for digest, occurrences in hash_to_occurrences.items():
        if len(occurrences) < 2:
            continue
        blocks.append({"hash": digest, "occurrences": occurrences})
    return blocks


def build_scope_entries(paths: list[Path], tier: int) -> list[dict]:
    entries: list[dict] = []
    for path in paths:
        measurements = measure_file(path)
        entries.append(
            {
                "path": str(path),
                "tier": tier,
                **measurements,
            }
        )
    return entries


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=os.getcwd(),
        help="Repository root (default: current working directory)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()

    home = Path(os.environ.get("HOME", str(Path.home()))).resolve()
    tier_1_paths = discover_tier_1(repo_root)
    tier_2_paths = discover_tier_2(tier_1_paths, repo_root)
    tier_3_paths = discover_tier_3(home)
    tier_4_paths = discover_tier_4(home, repo_root)
    scope = (
        build_scope_entries(tier_1_paths, tier=1)
        + build_scope_entries(tier_2_paths, tier=2)
        + build_scope_entries(tier_3_paths, tier=3)
        + build_scope_entries(tier_4_paths, tier=4)
    )

    per_tier: dict[str, int] = {}
    for entry in scope:
        key = str(entry["tier"])
        per_tier[key] = per_tier.get(key, 0) + entry["tokens_char4"]

    output = {
        "scope": scope,
        "dead_references": detect_dead_references(scope, repo_root),
        "duplicate_blocks": detect_duplicate_blocks(scope),
        "orphans": [],
        "token_baseline": {
            "per_file": {entry["path"]: entry["tokens_char4"] for entry in scope},
            "per_tier": per_tier,
            "total": sum(per_tier.values()),
        },
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
