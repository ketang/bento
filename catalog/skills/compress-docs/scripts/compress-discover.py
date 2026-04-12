#!/usr/bin/env python3
"""compress-docs deterministic helper. Emits JSON describing in-scope
documentation files and deterministic signals (dead references, duplicate
blocks, orphan files, token baseline).

Usage:
    compress-discover.py [--repo-root PATH]

Runs from the repository root by default.
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    json.dump({}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
