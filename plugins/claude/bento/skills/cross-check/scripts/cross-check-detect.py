#!/usr/bin/env python3
"""Bento cross-check counterpart detection.

Given the current agent runtime, reports whether the COUNTERPART runtime is
installed and authenticated, and recommends the 'cross' path or the same-runtime
'fallback'. Detection is best-effort: the real fallback trigger is the cross run
itself failing (see cross-check-run.py). See SKILL.md for the contract."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cross_check_common as common  # noqa: E402


def binary_available(name: str, *, which=shutil.which) -> bool:
    return which(name) is not None


def auth_ok(runtime: str, *, runner=None, timeout: int = 15) -> bool:
    cmd = common.AUTH_CMD[runtime]
    run = runner or _default_runner
    try:
        return run(cmd, timeout) == 0
    except Exception:
        return False


def _default_runner(cmd: list[str], timeout: int) -> int:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    ).returncode


def assess(current_runtime: str, *, which=shutil.which, auth=auth_ok) -> dict:
    counterpart = common.counterpart_of(current_runtime)
    on_path = binary_available(counterpart, which=which)
    authed = auth(counterpart) if on_path else False
    recommended = "cross" if (on_path and authed) else "fallback"
    if not on_path:
        reason = f"{counterpart} is not on PATH"
    elif not authed:
        reason = f"{counterpart} is on PATH but not authenticated"
    else:
        reason = f"{counterpart} is installed and authenticated"
    return {
        "current_runtime": current_runtime,
        "counterpart": counterpart,
        "counterpart_on_path": on_path,
        "counterpart_authenticated": authed,
        "recommended_path": recommended,
        "reason": reason,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cross-check-detect",
        description="Detect counterpart-runtime availability for cross-check.",
    )
    parser.add_argument(
        "--current-runtime",
        choices=sorted(common.COUNTERPART),
        help="the runtime invoking cross-check; counterpart is the other one. "
        "If omitted, inferred from environment (fails closed when ambiguous).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    current = args.current_runtime or common.infer_current_runtime()
    if current is None:
        print(
            "cross-check-detect: could not determine current runtime; "
            "pass --current-runtime claude|codex.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(assess(current), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
