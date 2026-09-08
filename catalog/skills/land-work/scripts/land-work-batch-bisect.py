#!/usr/bin/env python3
"""Bisect a red batch tip to isolate the culprit branch(es) (bento-faac).

land-work-batch-assemble.py assembles an ordered branch list into one
merge-commit chain but never gates it and never bisects a red result --
SKILL.md's "Batch Landing" step 4 gates the assembled tip separately, and
until this script existed, step 5 treated any red tip as a full stop: every
assembled branch returned as rework even when only one of them actually
caused the failure.

Given the same ordered branch list that just gated red at the tip (the
caller's job to have confirmed -- this script does not re-gate the full
list), this script bisects by halves in the same warm integration worktree:
split the list in two, reassemble each half against the leased base via
land-work-batch-assemble.py, run the gate command on each half, and recurse
into whichever half(ves) are still red. A red half of size one bottoms out
as a culprit -- no further split is possible. A half's own gate run counts
as evidence for that half specifically, not for its parent.

Non-monotonic interaction failures (a branch that is only red in
combination with another one, not alone) break the assumption ordinary
bisection relies on: neither half of a red parent is guaranteed to itself
be red. When halving finds *both* halves green despite their union being
known red, this script cannot localize further and marks the whole parent
subset "ambiguous_non_monotonic" -- every branch in it is reported as a
culprit, not just one. See references/batch-landing.md's "## Bisect"
section for the full rationale and the documented limitation.

Once bisection settles on a landable subset (the input branches minus every
culprit), that subset is reassembled fresh against the leased base and
gated once more to confirm -- catching an interaction failure among the
survivors themselves that pairwise halving alone would not (a residual risk
this script does not try to bisect further; a failure here is reported via
`final.ok: false` and the caller must treat it as a full stop for the whole
input, not just the branches already marked as culprits).

Emits one JSON object with the full trail (`trail`), the identified
culprits (`culprits`), the surviving landable subset (`landable`), and the
final confirmation attempt (`final`), or a structured `{ok: false, errors:
[...]}` payload (never an unhandled traceback) on an infra failure -- an
unregistered worktree, a bad base-ref, or the shared worktree becoming
unusable partway through (the same failure classes
land-work-batch-assemble.py itself degrades to a structured error for,
surfaced here through its own `errors`).
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import subprocess
import sys
from pathlib import Path

from git_state import NotAWorkTreeError, detect_checkout_root

SCRIPT_DIR = Path(__file__).resolve().parent
ASSEMBLE_SCRIPT = SCRIPT_DIR / "land-work-batch-assemble.py"


class AssembleFailedError(RuntimeError):
    """Raised when a bisection subset failed to assemble (an infra failure,
    not a red gate) -- aborts the whole bisect rather than bisecting further
    against a worktree that may no longer be trustworthy."""

    def __init__(self, payload: dict) -> None:
        super().__init__("; ".join(payload.get("errors") or ["assemble failed"]))
        self.payload = payload


def _tail_lines(text: str, count: int) -> list[str]:
    """Last `count` lines of text without materializing the whole line list
    first -- mirrors land-work-run-verifier.py's `_tail_lines`, kept as its
    own copy here rather than a cross-script import: a gate command's output
    is unrelated to that script's verifier-log concern, and cross-importing
    a private helper across scripts would couple two otherwise-independent
    landing steps for one small function."""
    tail: collections.deque[str] = collections.deque(maxlen=count)
    start = 0
    for index, char in enumerate(text):
        if char == "\n":
            tail.append(text[start:index])
            start = index + 1
    if start < len(text):
        tail.append(text[start:])
    return list(tail)


def run_assemble(worktree: Path, base_ref: str, branches: list[str]) -> dict:
    args = [str(ASSEMBLE_SCRIPT), "--worktree", str(worktree), "--base-ref", base_ref]
    args.extend(itertools.chain.from_iterable(("--branch", b) for b in branches))
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        raise AssembleFailedError(
            {
                "ok": False,
                "errors": [
                    f"land-work-batch-assemble.py produced non-JSON output for "
                    f"branches {branches!r} (exit {proc.returncode}): {exc}; "
                    f"stderr: {proc.stderr.strip()}"
                ],
            }
        ) from exc
    if not payload.get("ok"):
        raise AssembleFailedError(payload)
    return payload


def run_gate(command: str, worktree: Path) -> dict:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout_tail": [],
            "stderr_tail": [str(exc)],
            "passed": False,
            "launch_error": str(exc),
        }
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout_tail": _tail_lines(proc.stdout, 20),
        "stderr_tail": _tail_lines(proc.stderr, 20),
        "passed": proc.returncode == 0,
    }


class Bisector:
    def __init__(self, worktree: Path, base_ref: str, gate_command: str) -> None:
        self.worktree = worktree
        self.base_ref = base_ref
        self.gate_command = gate_command
        self.trail: list[dict] = []
        self._next_index = itertools.count(1)

    def attempt(self, branches: list[str]) -> tuple[dict, dict]:
        assemble_payload = run_assemble(self.worktree, self.base_ref, branches)
        gate_payload = run_gate(self.gate_command, self.worktree)
        result = "green" if gate_payload["passed"] else "red"
        self.trail.append(
            {
                "kind": "attempt",
                "index": next(self._next_index),
                "branches": list(branches),
                "assemble": assemble_payload,
                "gate": gate_payload,
                "result": result,
            }
        )
        return assemble_payload, gate_payload

    def note(self, branches: list[str], message: str) -> None:
        self.trail.append(
            {
                "kind": "note",
                "branches": list(branches),
                "message": message,
            }
        )

    def bisect(self, branches: list[str]) -> list[str]:
        """Given a subset already known red (by construction: the top-level
        call is red per the caller's contract, and every recursive call is
        only made on a half whose own gate attempt just came back red),
        return the culprit branch(es) within it.
        """
        if len(branches) == 1:
            # Nothing smaller to split into; the parent's own attempt at
            # this branch already produced the "red" verdict recorded in
            # the trail, so no further gate run is needed here.
            return list(branches)

        mid = len(branches) // 2
        halves = [branches[:mid], branches[mid:]]
        culprits: list[str] = []
        any_half_red = False

        for half in halves:
            _, gate_payload = self.attempt(half)
            if not gate_payload["passed"]:
                any_half_red = True
                culprits.extend(self.bisect(half))

        if not any_half_red:
            # Non-monotonic interaction: neither half alone reproduced the
            # parent's red result, yet the union (branches) is known red.
            # Halving cannot localize further -- attribute the whole
            # parent subset.
            self.note(
                branches,
                "ambiguous_non_monotonic: neither half gated red alone, but "
                "the combined subset is known red; halving cannot isolate a "
                "single culprit here, so every branch in this subset is "
                "reported as a culprit",
            )
            return list(branches)

        return culprits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, help="warm integration worktree, already at a red assembled tip")
    parser.add_argument("--base-ref", required=True, help="leased base revision to reassemble each subset against")
    parser.add_argument(
        "--gate-command",
        required=True,
        help="landing.full_gate shell command, run in the worktree for every reassembled subset",
    )
    parser.add_argument(
        "--branch",
        action="append",
        default=[],
        dest="branches",
        help="branch in the red batch, in order; repeat for each branch (at least 2 required)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cwd = Path.cwd().resolve()
    checkout_root = detect_checkout_root(cwd)
    worktree = Path(args.worktree).resolve()

    def emit(
        *,
        ok: bool,
        errors: list[str],
        trail: list[dict] | None = None,
        culprits: list[str] | None = None,
        landable: list[str] | None = None,
        final: dict | None = None,
    ) -> int:
        payload = {
            "cwd": str(cwd),
            "checkout_root": str(checkout_root),
            "worktree": str(worktree),
            "base_ref": args.base_ref,
            "gate_command": args.gate_command,
            "input_branches": args.branches,
            "trail": trail or [],
            "culprits": culprits or [],
            "landable": landable or [],
            "final": final,
            "ok": ok,
            "errors": errors,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if ok else 1

    if len(args.branches) < 2:
        return emit(
            ok=False,
            errors=[
                f"--branch given {len(args.branches)} time(s); bisect requires at "
                "least 2 -- a single-branch red batch is already its own culprit "
                "and does not need this script"
            ],
        )

    bisector = Bisector(worktree, args.base_ref, args.gate_command)
    try:
        culprits = bisector.bisect(list(args.branches))
    except AssembleFailedError as exc:
        return emit(
            ok=False,
            errors=[f"assembling a bisection subset failed: {exc}"],
            trail=bisector.trail,
        )

    culprit_set = set(culprits)
    landable = [b for b in args.branches if b not in culprit_set]

    final: dict | None = None
    if landable:
        try:
            final_assemble, final_gate = bisector.attempt(landable)
        except AssembleFailedError as exc:
            return emit(
                ok=False,
                errors=[f"final confirmation assemble of the landable subset failed: {exc}"],
                trail=bisector.trail,
                culprits=culprits,
                landable=landable,
            )
        final = {
            "assemble": final_assemble,
            "gate": final_gate,
            "ok": bool(final_gate["passed"]),
        }
        if not final["ok"]:
            bisector.note(
                landable,
                "final confirmation gate failed on the subset bisection identified "
                "as landable: a non-monotonic interaction survived pairwise "
                "halving. Treat this as a full stop for the whole input batch, "
                "not just `culprits` -- do not land `landable` as-is.",
            )

    return emit(
        ok=True,
        errors=[],
        trail=bisector.trail,
        culprits=culprits,
        landable=landable,
        final=final,
    )


if __name__ == "__main__":
    try:
        exit_code = main()
    except NotAWorkTreeError as exc:
        json.dump(exc.diagnostic, sys.stdout, indent=2)
        sys.stdout.write("\n")
        exit_code = 1
    raise SystemExit(exit_code)
