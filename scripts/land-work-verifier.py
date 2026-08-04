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
    # Plain pytest, not scripts/run-tests-with-skip-policy.py: that script's
    # expected-skip set assumes a clean CI runner. Run nested inside an
    # active agent session (the common case for a land-work verifier),
    # several tests skip for a different, still-legitimate reason (no
    # spawned claude/codex CLI to avoid inheriting the outer session's auth
    # state), which would make the skip-policy script fail closed on a
    # correct candidate. CI keeps the strict skip-policy check separately.
    ("pytest tests", [sys.executable, "-m", "pytest", "tests", "-q"]),
    ("check-cli-arg-parity", [sys.executable, "scripts/check-cli-arg-parity"]),
    ("check-temporal-claims", [sys.executable, "scripts/check-temporal-claims"]),
]


def main() -> int:
    selected_checks = []
    overall = "passed"
    for name, cmd in CHECKS:
        print(f"==> {name}", file=sys.stderr)
        # Route child stdout to our stderr so the JSON result below stays
        # the only thing this script ever writes to stdout.
        result = subprocess.run(cmd, cwd=REPO_ROOT, stdout=sys.stderr, stderr=sys.stderr)
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
