#!/usr/bin/env python3
"""Project verifier for land-work's project-verifier gate (bento-mqdt).

Runs bento's own CI-equivalent gate suite against the candidate worktree and
reports the schema_version:1 result land-work-run-verifier.py expects. See
catalog/skills/land-work/references/project-verifier.md for the contract.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CHECKS: list[tuple[str, list[str]]] = [
    ("build-plugins --check", [sys.executable, "scripts/build-plugins", "--check"]),
    ("pytest tests", [sys.executable, "-m", "pytest", "tests", "-q"]),
    ("check-cli-arg-parity", [sys.executable, "scripts/check-cli-arg-parity"]),
    ("check-temporal-claims", [sys.executable, "scripts/check-temporal-claims"]),
]


def main() -> int:
    selected_checks = []
    overall = "passed"
    for name, cmd in CHECKS:
        print(f"==> {name}", file=sys.stderr)
        result = subprocess.run(cmd, cwd=REPO_ROOT)
        status = "passed" if result.returncode == 0 else "failed"
        if status == "failed":
            overall = "failed"
        selected_checks.append({"name": name, "status": status})
    print(json.dumps({
        "schema_version": 1,
        "status": overall,
        "selected_checks": selected_checks,
    }))
    return 0 if overall == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
