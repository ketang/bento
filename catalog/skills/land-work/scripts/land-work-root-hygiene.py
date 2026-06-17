#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from git_state import detect_checkout_root, git, primary_checkout_root


def untracked_paths(root: Path) -> list[str]:
    # porcelain without --ignored already omits gitignored paths; -z gives NUL-separated unquoted names
    result = git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "-z",
        cwd=root,
    )
    paths: list[str] = []
    for entry in result.stdout.split("\0"):
        if entry[:2] == "??":
            paths.append(entry[3:])
    return sorted(paths)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the primary checkout root for untracked files not covered "
            "by .gitignore. Advisory post-landing hygiene check (land-work "
            "step 9a)."
        )
    )
    parser.add_argument(
        "--root",
        help="primary checkout root to audit; defaults to the primary checkout of the current repo",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    root = Path(args.root).resolve() if args.root else primary_checkout_root(checkout_root)

    paths = untracked_paths(root)

    payload = {
        "cwd": str(cwd),
        "primary_checkout_root": str(root),
        "untracked_paths": paths,
        "clean": not paths,
        "ok": True,
    }

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
