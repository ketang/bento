#!/usr/bin/env python3
"""CLI front end for project extensions discovery and hook execution.

Subcommands:
    discover    List extensions in execution order as JSON.
    run-hooks   Execute hooks at a position with the env-var protocol.

The importable logic lives in bento_extensions.py beside this script.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_module():
    path = SCRIPT_DIR / "bento_extensions.py"
    spec = importlib.util.spec_from_file_location("bento_extensions", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass field-type resolution can find the
    # module via sys.modules during class construction.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cmd_discover(args: argparse.Namespace) -> int:
    bento_extensions = _load_module()
    result = bento_extensions.discover(
        repo_root=Path(args.repo_root).resolve(),
        skill=args.skill,
        kind=args.kind,
        position=args.position,
    )
    json.dump(
        {
            "files": [str(p) for p in result.files],
            "warnings": result.warnings,
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_disc = sub.add_parser("discover", help="list extensions as JSON")
    p_disc.add_argument("--repo-root", required=True)
    p_disc.add_argument("--skill", required=True, choices=["launch-work", "land-work"])
    p_disc.add_argument("--kind", required=True, choices=["hooks", "actions"])
    p_disc.add_argument("--position", required=True, choices=["pre", "post"])
    p_disc.set_defaults(func=_cmd_discover)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
