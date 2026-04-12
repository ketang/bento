#!/usr/bin/env python3
"""compress-docs deterministic helper. Emits JSON describing in-scope
documentation files and deterministic signals (dead references, duplicate
blocks, orphan files, token baseline).

Usage:
    compress-discover.py [--repo-root PATH]
"""
from __future__ import annotations

import argparse
import json
import os
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

    tier_1_paths = discover_tier_1(repo_root)
    scope = build_scope_entries(tier_1_paths, tier=1)

    output = {
        "scope": scope,
        "dead_references": [],
        "duplicate_blocks": [],
        "orphans": [],
        "token_baseline": {
            "per_file": {entry["path"]: entry["tokens_char4"] for entry in scope},
            "per_tier": {"1": sum(e["tokens_char4"] for e in scope)},
            "total": sum(e["tokens_char4"] for e in scope),
        },
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
