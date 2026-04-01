#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from git_state import current_branch, detect_checkout_root, detect_primary_branch, is_linked_worktree, ref_exists, rev_parse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", help="ref to verify; defaults to origin/<primary-branch> when available")
    parser.add_argument("--expected-sha", help="required SHA for the ref")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    primary_branch, warnings = detect_primary_branch(checkout_root)
    branch = current_branch(checkout_root)
    default_ref = (
        f"refs/remotes/origin/{primary_branch}"
        if ref_exists(f"refs/remotes/origin/{primary_branch}", checkout_root)
        else f"refs/heads/{primary_branch}"
    )
    ref = args.ref or default_ref

    errors: list[str] = []
    resolved_sha = None
    if not ref_exists(ref, checkout_root):
        errors.append(f"ref does not exist: {ref}")
    else:
        resolved_sha = rev_parse(ref, checkout_root)

    lease_matches = args.expected_sha is None or resolved_sha == args.expected_sha
    if args.expected_sha is not None and not lease_matches:
        errors.append(f"lease mismatch for {ref}")

    payload = {
        "cwd": str(cwd),
        "checkout_root": str(checkout_root),
        "branch": branch,
        "primary_branch": primary_branch,
        "linked_worktree": is_linked_worktree(checkout_root),
        "ref": ref,
        "resolved_sha": resolved_sha,
        "expected_sha": args.expected_sha,
        "lease_matches": lease_matches,
        "ok": not errors,
        "warnings": warnings,
        "errors": errors,
    }

    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
