#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


HOOKS = {"rebase-landing-target-onto-primary"}


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def rebase_landing_target_onto_primary(landing_target: str, primary: str, cwd: Path, apply: bool) -> dict[str, object]:
    current = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    current_branch = current.stdout.strip()
    errors: list[str] = []

    if apply and current_branch != landing_target:
        errors.append(f"must run on the landing target branch: expected {landing_target}, got {current_branch}")

    if apply and not errors:
        rebase = run_git(["rebase", primary], cwd)
        if rebase.returncode != 0:
            errors.append(rebase.stderr.strip() or rebase.stdout.strip())

    return {
        "hook": "rebase-landing-target-onto-primary",
        "landing_target": landing_target,
        "primary": primary,
        "current_branch": current_branch,
        "applied": apply and not errors,
        "ok": not errors,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="swarm-post-land")
    parser.add_argument("--hook", required=True, choices=sorted(HOOKS))
    parser.add_argument("--landing-target", required=True)
    parser.add_argument("--primary", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    cwd = Path.cwd().resolve()
    if args.hook == "rebase-landing-target-onto-primary":
        payload = rebase_landing_target_onto_primary(args.landing_target, args.primary, cwd, args.apply)
    else:
        payload = {"ok": False, "errors": [f"unknown hook: {args.hook}"]}

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
