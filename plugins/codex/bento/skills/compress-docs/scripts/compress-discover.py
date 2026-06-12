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
# Claude Code `@path` imports: recognized at start-of-line or after whitespace
# (so `user@host` email addresses are not matched), path runs to the next space.
AT_INCLUDE_RE = re.compile(r"(?:^|(?<=\s))@([^\s`]+)", re.MULTILINE)


def extract_references(text: str) -> list[str]:
    refs: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        refs.append(match.group(1))
    for match in BACKTICK_PATH_RE.finditer(text):
        candidate = match.group(1).strip()
        if "/" in candidate or candidate.endswith(".md"):
            refs.append(candidate)
    for match in AT_INCLUDE_RE.finditer(text):
        refs.append(match.group(1))
    return refs


def resolve_reference(
    ref: str, source_file: Path, repo_root: Path, *, allow_external: bool = False
) -> Path | None:
    if ref.startswith(("http://", "https://", "mailto:")):
        return None
    ref_clean = ref.split("#", 1)[0].split("?", 1)[0]
    if not ref_clean:
        return None
    expanded = os.path.expanduser(ref_clean)
    base = Path(expanded)
    if base.is_absolute():
        candidate = base.resolve()
    else:
        candidate = (source_file.parent / expanded).resolve()
    if not allow_external:
        try:
            candidate.relative_to(repo_root)
        except ValueError:
            return None
    if not candidate.is_file():
        return None
    return candidate


def _follow_references(
    seeds: list[Path],
    repo_root: Path,
    *,
    max_depth: int,
    allow_external: bool,
    already_visited: set[Path] | None = None,
) -> list[Path]:
    """Breadth-first crawl of references reachable from *seeds*.

    Returns newly discovered files (excludes the seeds and any path in
    *already_visited*). With *allow_external* set, references resolving outside
    *repo_root* are followed — used for user-global docs whose `@`-imports point
    into a dotfiles tree outside the project."""
    visited: set[Path] = set(seeds)
    if already_visited:
        visited |= already_visited
    discovered: set[Path] = set()
    frontier: list[tuple[Path, int]] = [(p, 0) for p in seeds]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        try:
            text = current.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ref in extract_references(text):
            resolved = resolve_reference(
                ref, current, repo_root, allow_external=allow_external
            )
            if resolved is None or resolved in visited:
                continue
            visited.add(resolved)
            discovered.add(resolved)
            frontier.append((resolved, depth + 1))
    return sorted(discovered)


def discover_tier_2(tier_1_paths: list[Path], repo_root: Path) -> list[Path]:
    return _follow_references(
        tier_1_paths,
        repo_root,
        max_depth=TIER_2_MAX_DEPTH,
        allow_external=False,
    )


TIER_3_USER_GLOBAL = ".claude/CLAUDE.md"
TIER_3_MAX_DEPTH = 3
TIER_4_MEMORY_DIR = ".claude/projects"
TIER_4_MEMORY_SUBDIR = "memory"


def discover_tier_3(home: Path, repo_root: Path, already_visited: set[Path]) -> list[Path]:
    candidate = home / TIER_3_USER_GLOBAL
    if not candidate.is_file():
        return []
    seed = candidate.resolve()
    chained = _follow_references(
        [seed],
        repo_root,
        max_depth=TIER_3_MAX_DEPTH,
        allow_external=True,
        already_visited=already_visited,
    )
    return sorted({seed, *chained})


def project_memory_slug(repo_root: Path) -> str:
    return str(repo_root).replace("/", "-").lstrip("-")


def discover_tier_4(home: Path, repo_root: Path) -> list[Path]:
    slug = project_memory_slug(repo_root)
    memory_dir = home / TIER_4_MEMORY_DIR / slug / TIER_4_MEMORY_SUBDIR
    if not memory_dir.is_dir():
        return []
    return sorted(p.resolve() for p in memory_dir.glob("*.md") if p.is_file())


COMMAND_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
PATH_EXTENSIONS = (
    ".md", ".py", ".sh", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".toml", ".txt", ".cfg",
    ".ini", ".rs", ".go", ".rb", ".lua",
)
# Launchers that mark a backticked token as an actual command invocation.
COMMAND_LAUNCHERS = frozenset({
    "git", "npm", "pnpm", "yarn", "npx", "node", "deno", "bun",
    "bd", "rtk", "make", "cargo", "go", "rustc",
    "python", "python3", "pip", "pip3", "pytest", "ruff", "mypy", "uv",
    "docker", "kubectl", "helm", "gh", "bash", "sh", "zsh", "curl",
})


def classify_backtick_content(content: str) -> str:
    if "/" in content or content.endswith(PATH_EXTENSIONS):
        return "path"
    # Only treat backticked content as a command when there is positive evidence
    # of an invocation: a recognized launcher, or a multi-token invocation whose
    # first token looks like a command name. A lone backticked word (a flag,
    # reason code, config key, or ordinary prose) is "other" — never a command.
    tokens = content.split()
    if not tokens:
        return "other"
    first = tokens[0]
    if first in COMMAND_LAUNCHERS:
        return "command"
    if len(tokens) >= 2 and COMMAND_NAME_RE.match(first):
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
                cmd = ref.split()[0]
                if shutil.which(cmd) is None and not (repo_root / "scripts" / cmd).exists():
                    resolution = "missing"
            if resolution == "missing":
                record = {
                    "source": str(path),
                    "line": lineno,
                    "reference": ref,
                    "kind": kind,
                    "resolution": "missing",
                }
                # Command resolution is environment-dependent (a tool may exist
                # in CI but not locally), so command findings are advisory, not
                # hard delete candidates the way missing paths are.
                if kind == "command":
                    record["advisory"] = True
                dead.append(record)
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


def detect_orphans(tier_1_paths: list[Path], repo_root: Path) -> list[str]:
    top_level = {repo_root / name for name in TIER_1_TOP_LEVEL_NAMES}
    top_level = {p.resolve() for p in top_level if p.is_file()}
    nested = [p for p in tier_1_paths if p not in top_level]
    if not nested:
        return []
    referenced: set[Path] = set()
    for source in tier_1_paths:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ref in extract_references(text):
            resolved = resolve_reference(ref, source, repo_root)
            if resolved is not None:
                referenced.add(resolved)
    return sorted(str(p) for p in nested if p not in referenced)


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
    tier_3_paths = discover_tier_3(
        home, repo_root, already_visited=set(tier_1_paths) | set(tier_2_paths)
    )
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
        "orphans": detect_orphans(tier_1_paths, repo_root),
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
