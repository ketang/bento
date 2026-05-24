#!/usr/bin/env python3
"""CLI front end for project extensions discovery and hook execution.

Subcommands:
    discover    List extensions in execution order as JSON.
    run-hooks   Execute hooks at a position with the env-var protocol.

The importable logic lives in lifecycle_extensions.py beside this script.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_module():
    path = SCRIPT_DIR / "lifecycle_extensions.py"
    spec = importlib.util.spec_from_file_location("lifecycle_extensions", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass field-type resolution can find the
    # module via sys.modules during class construction.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cmd_discover(args: argparse.Namespace) -> int:
    lifecycle_extensions = _load_module()
    result = lifecycle_extensions.discover(
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


def _cmd_run_hooks(args: argparse.Namespace) -> int:
    lifecycle_extensions = _load_module()
    result = lifecycle_extensions.discover(
        repo_root=Path(args.repo_root).resolve(),
        skill=args.skill,
        kind="hook-scripts",
        position=args.position,
    )
    for warning in result.warnings:
        print(f"[run-lifecycle-extensions] WARNING: {warning}", file=sys.stderr)

    ctx = lifecycle_extensions.HookContext(
        repo_root=Path(args.repo_root).resolve(),
        skill=args.skill,
        position=args.position,
        branch=args.branch,
        worktree=args.worktree,
        base_ref=args.base_ref,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        merge_sha=args.merge_sha,
        landed=args.landed,
        runtime=args.runtime,
        task_id=args.task_id,
        timeout=args.timeout,
    )

    cwd = Path(args.worktree) if args.worktree else Path(args.repo_root)
    overall, outcomes = lifecycle_extensions.run_hooks(
        hooks=result.files,
        ctx=ctx,
        advisory=args.advisory,
        cwd=cwd,
        parent_env=os.environ.copy(),
    )

    for outcome in outcomes:
        marker = "OK" if outcome.returncode == 0 else (
            "TIMEOUT" if outcome.timed_out else f"EXIT {outcome.returncode}"
        )
        print(
            f"[run-lifecycle-extensions] {outcome.path.name}: {marker}",
            file=sys.stderr,
        )

    return overall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_disc = sub.add_parser("discover", help="list extensions as JSON")
    p_disc.add_argument("--repo-root", required=True)
    p_disc.add_argument("--skill", required=True, choices=["launch-work", "land-work"])
    p_disc.add_argument("--kind", required=True, choices=["hook-scripts", "hook-skills"])
    p_disc.add_argument("--position", required=True, choices=["pre", "post"])
    p_disc.set_defaults(func=_cmd_discover)

    p_run = sub.add_parser("run-hooks", help="execute hooks at a position")
    p_run.add_argument("--repo-root", required=True)
    p_run.add_argument("--skill", required=True, choices=["launch-work", "land-work"])
    p_run.add_argument("--position", required=True, choices=["pre", "post"])
    p_run.add_argument("--branch", default="")
    p_run.add_argument("--worktree", default="")
    p_run.add_argument("--base-ref", default="")
    p_run.add_argument("--base-sha", default="")
    p_run.add_argument("--head-sha", default="")
    p_run.add_argument("--merge-sha", default="")
    p_run.add_argument("--landed", default="")
    p_run.add_argument("--runtime", default="unknown")
    p_run.add_argument("--task-id", default="")
    p_run.add_argument("--timeout", default="")
    p_run.add_argument("--advisory", action="store_true")
    p_run.set_defaults(func=_cmd_run_hooks)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
