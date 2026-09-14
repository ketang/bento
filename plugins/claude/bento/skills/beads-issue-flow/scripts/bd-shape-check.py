#!/usr/bin/env python3
"""Verify the bd CLI shapes documented in beads-issue-flow/SKILL.md's
"CLI shapes" section still hold against the installed ``bd`` binary.

Read-only: never creates, updates, or deletes an issue. Run this as the
manual re-verification step whenever bumping metadata.json's
verified_bd_version pin -- if it reports a FAIL, update both the SKILL.md
section and the pin together. It also runs automatically in bento's own
test suite, where it is skipped (not failed) when ``bd`` is not on PATH, so
a repo without bd installed never fails CI over this.

Exit 0 on success (including an all-skip run); exit 1 if any shape failed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bd", *args], capture_output=True, text=True, check=False)


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def ok(self, name: str) -> None:
        print(f"[OK]   {name}")

    def fail(self, name: str, detail: str) -> None:
        self.failed = True
        print(f"[FAIL] {name} -- {detail}")

    def skip(self, name: str, detail: str) -> None:
        print(f"[SKIP] {name} -- {detail}")


def _parse_json_list(proc: subprocess.CompletedProcess[str], name: str, r: Reporter) -> list | None:
    if proc.returncode != 0:
        r.fail(name, (proc.stderr or proc.stdout).strip())
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        r.fail(name, f"unparseable: {exc}")
        return None
    if not isinstance(data, list):
        r.fail(name, f"got {type(data).__name__}, not a list")
        return None
    r.ok(name)
    return data


def check_list_returns_bare_list(r: Reporter) -> list | None:
    return _parse_json_list(
        _run("list", "--json", "--limit", "1"), "bd list --json returns a bare list", r
    )


def check_show_returns_one_element_list(r: Reporter, sample_issues: list) -> None:
    name = "bd show <id> --json returns a one-element list"
    if not sample_issues:
        r.skip(name, "no issues in this db to sample")
        return
    issue_id = sample_issues[0].get("id")
    if not issue_id:
        r.skip(name, "sample issue had no 'id' field")
        return
    data = _parse_json_list(_run("show", issue_id, "--json"), name, r)
    if data is not None and len(data) != 1:
        r.failed = True
        print(f"[FAIL] {name} -- expected exactly one element, got {len(data)}")


def check_ready_returns_bare_list(r: Reporter) -> list | None:
    return _parse_json_list(
        _run("ready", "--json", "--limit", "0"), "bd ready --json returns a bare list", r
    )


def check_ready_limit_trailer_on_stderr(r: Reporter, total_ready: int) -> None:
    name = "bd ready --json --limit <n> puts its truncation notice on stderr, not stdout"
    if total_ready < 2:
        r.skip(name, f"only {total_ready} ready issue(s) in this db; need >= 2 to observe truncation")
        return
    proc = _run("ready", "--json", "--limit", "1")
    if proc.returncode != 0:
        r.fail(name, (proc.stdout or "").strip())
        return
    try:
        json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        r.fail(name, f"stdout alone did not parse as clean JSON: {exc}")
        return
    if "Showing" in proc.stderr and "ready issues" in proc.stderr:
        r.ok(name)
    else:
        r.fail(name, "expected truncation notice not found on stderr -- SKILL.md may be stale")


def check_search_returns_bare_list(r: Reporter) -> None:
    _parse_json_list(
        _run("search", "a", "--json", "--limit", "1"),
        "bd search <query> --json returns a bare list",
        r,
    )


def check_create_flags(r: Reporter) -> None:
    name = "bd create flag surface (-t/--type, --notes, -d/--description; no --issue-type/--note/--comment)"
    help_text = _run("create", "--help").stdout
    absent = all(flag not in help_text for flag in ("--issue-type", "--note ", "--comment"))
    present = all(flag in help_text for flag in ("-t, --type", "--notes", "-d, --description"))
    if absent and present:
        r.ok(name)
    else:
        r.fail(name, f"absent_ok={absent} present_ok={present}")


def _has_flag_shorthand(help_text: str, shorthand: str) -> bool:
    """True when help_text declares a flag whose short form is exactly
    ``-<shorthand>`` (cobra's own "-x, --longflag" line convention, line-
    anchored so this can't match "-m" appearing mid-sentence in a
    description -- more robust than a bare substring search against a
    reformatted or reflowed --help output)."""
    return bool(re.search(rf"(?m)^\s*-{re.escape(shorthand)},\s+--", help_text))


def check_update_flags(r: Reporter) -> None:
    name = "bd update flag surface (--notes/--append-notes; no --reason/-m/--message)"
    help_text = _run("update", "--help").stdout
    absent = (
        "--reason" not in help_text
        and not _has_flag_shorthand(help_text, "m")
        and "--message" not in help_text
    )
    present = "--notes" in help_text and "--append-notes" in help_text
    if absent and present:
        r.ok(name)
    else:
        r.fail(name, f"absent_ok={absent} present_ok={present}")


def check_close_reason_flag(r: Reporter) -> None:
    name = "bd close --reason/-r flag"
    help_text = _run("close", "--help").stdout
    if "-r, --reason" in help_text:
        r.ok(name)
    else:
        r.fail(name, "-r, --reason not found in bd close --help")


def check_dep_add_arg_order(r: Reporter) -> None:
    """Verifies the documented (blocked-id, blocker-id) argument order for
    `bd dep add`, not merely that the subcommand exists -- bd's own --help
    states this equivalence to the recommended --blocks form verbatim, so
    matching that exact line ties the check to the order itself, the actual
    error-prone claim SKILL.md makes."""
    name = "bd dep add <blocked-id> <blocker-id> argument order (equivalence to the --blocks form)"
    help_text = _run("dep", "--help").stdout
    if "bd dep add <blocked-id> <blocker-id>" in help_text:
        r.ok(name)
    else:
        r.fail(
            name,
            "expected equivalence line 'bd dep add <blocked-id> <blocker-id>' not found in "
            "bd dep --help -- the argument order (or its documentation) may have changed",
        )


def main() -> int:
    if shutil.which("bd") is None:
        print("bd not found on PATH; skipping CLI shape checks.")
        return 0

    r = Reporter()
    listed = check_list_returns_bare_list(r) or []
    check_show_returns_one_element_list(r, listed)
    ready = check_ready_returns_bare_list(r) or []
    check_ready_limit_trailer_on_stderr(r, len(ready))
    check_search_returns_bare_list(r)
    check_create_flags(r)
    check_update_flags(r)
    check_close_reason_flag(r)
    check_dep_add_arg_order(r)

    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
