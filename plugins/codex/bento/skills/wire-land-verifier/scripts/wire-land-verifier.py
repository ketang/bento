#!/usr/bin/env python3
"""Scaffold land-work's project verifier for a repository (bento-ei1p).

`land-work` fails closed when a repo has no
`.agent-plugins/bento/bento/land-work/verifier.json`. This CLI is the on-ramp:
it *proposes* candidate gate commands, then stages, validates, and installs a
wrapper script plus manifest that satisfy
`catalog/skills/land-work/references/project-verifier.md` unchanged.

The trust property land-work exists to enforce is that a landing never passes
against a zero-check result, so this CLI never picks a gate command on its own:

* `discover` only reports candidates; it writes nothing.
* `draft` requires explicit `--check` values and rejects no-op commands and
  commands whose executable does not resolve.
* `validate` actually runs the staged wrapper and records a receipt.
* `apply` refuses unless a receipt matches the current draft and reported at
  least one selected check.

Subcommands: discover, draft, validate, apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

MANIFEST_REL = Path(".agent-plugins/bento/bento/land-work/verifier.json")
DEFAULT_WRAPPER_REL = "scripts/land-work-verifier.py"
STAGING_REL = Path("bento/wire-land-verifier")

# Commands that would make the verifier rubber-stamp a landing. A wrapper built
# from any of these reports "passed" while checking nothing.
NO_OP_EXECUTABLES = frozenset({"true", ":", "echo", "printf", "exit", "test"})

# Target/script names that usually mean "run everything" rather than one narrow
# step. Used only to rank proposals; never to select one.
AGGREGATE_NAMES = (
    "ci",
    "check",
    "checks",
    "gate",
    "verify",
    "validate",
    "all",
    "test",
    "tests",
    "quality",
    "precommit",
    "pre-commit",
    "lint",
)

_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.\-/]*)\s*:(?!=)")
_JUST_RECIPE_RE = re.compile(r"^([a-z0-9][a-z0-9_-]*)(?:\s+[^:]*)?:(?!=)")
_WORKFLOW_RUN_RE = re.compile(r"^\s*(?:-\s+)?run:\s*(\S.*?)\s*$")


class WireError(RuntimeError):
    """A user-correctable problem; reported without a traceback."""


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def _rank(name: str) -> int:
    """Lower sorts first. Aggregate-looking names rank above narrow ones."""
    lowered = name.lower()
    for index, candidate in enumerate(AGGREGATE_NAMES):
        if lowered == candidate:
            return index
    return len(AGGREGATE_NAMES)


def _make_targets(worktree: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for filename in ("Makefile", "makefile", "GNUmakefile"):
        path = worktree / filename
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(("\t", " ", "#")):
                continue
            match = _MAKE_TARGET_RE.match(line)
            if match and not match.group(1).startswith("."):
                found.append((match.group(1), filename))
        break
    return found


def _package_scripts(worktree: Path) -> list[str]:
    path = worktree / "package.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    scripts = data.get("scripts")
    return sorted(scripts) if isinstance(scripts, dict) else []


def _just_recipes(worktree: Path) -> list[str]:
    for filename in ("justfile", "Justfile", ".justfile"):
        path = worktree / filename
        if not path.is_file():
            continue
        found = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith((" ", "\t", "#")):
                continue
            match = _JUST_RECIPE_RE.match(line)
            if match:
                found.append(match.group(1))
        return found
    return []


def _workflow_runs(worktree: Path) -> list[tuple[str, str]]:
    """Single-line `run:` steps from GitHub workflows.

    Block scalars (`run: |`) are skipped deliberately: a multi-line step is a
    script, not a command an argv-based verifier can wrap directly.
    """
    workflows = worktree / ".github" / "workflows"
    if not workflows.is_dir():
        return []
    found: list[tuple[str, str]] = []
    for path in sorted(workflows.glob("*.y*ml")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _WORKFLOW_RUN_RE.match(line)
            if not match:
                continue
            command = match.group(1).strip().strip("\"'")
            if command in {"|", ">", "|-", ">-"} or not command:
                continue
            found.append((command, str(path.relative_to(worktree))))
    return found


def discover(worktree: Path) -> dict:
    candidates: list[dict] = []

    for target, source in _make_targets(worktree):
        candidates.append(
            {"command": f"make {target}", "source": source, "rank": _rank(target)}
        )
    for script in _package_scripts(worktree):
        candidates.append(
            {
                "command": f"npm run {script}",
                "source": "package.json",
                "rank": _rank(script),
            }
        )
    for recipe in _just_recipes(worktree):
        candidates.append(
            {"command": f"just {recipe}", "source": "justfile", "rank": _rank(recipe)}
        )
    for command, source in _workflow_runs(worktree):
        first_word = shlex.split(command)[0] if command.strip() else ""
        candidates.append(
            {"command": command, "source": source, "rank": _rank(first_word)}
        )

    seen: set[str] = set()
    unique: list[dict] = []
    for candidate in sorted(candidates, key=lambda c: (c["rank"], c["command"])):
        if candidate["command"] in seen:
            continue
        seen.add(candidate["command"])
        unique.append(candidate)

    return {
        "worktree": str(worktree),
        "candidates": unique,
        "note": (
            "Proposals only. Confirm with the repo owner which command(s) are "
            "the real landing gate before drafting; nothing was written."
        ),
    }


# --------------------------------------------------------------------------
# draft
# --------------------------------------------------------------------------


def parse_check(raw: str) -> dict:
    """Parse a ``NAME::COMMAND`` (or bare ``COMMAND``) --check value."""
    name, separator, command = raw.partition("::")
    if not separator:
        name, command = raw.strip(), raw.strip()
    name, command = name.strip(), command.strip()
    if not name or not command:
        raise WireError(f"--check {raw!r} is empty; use 'NAME::COMMAND' or 'COMMAND'")
    try:
        argv = shlex.split(command)
    except ValueError as error:
        raise WireError(f"--check {raw!r} is not parseable: {error}") from error
    if not argv:
        raise WireError(f"--check {raw!r} has no command")
    return {"name": name, "command": command, "argv": argv}


def reject_no_ops(check: dict) -> None:
    argv = check["argv"]
    head = Path(argv[0]).name
    if head in NO_OP_EXECUTABLES:
        raise WireError(
            f"--check {check['command']!r} is a no-op command ({head!r}). A verifier "
            "built from it would report 'passed' without checking the diff, which "
            "is exactly what land-work's gate exists to prevent."
        )
    if head in {"sh", "bash", "zsh"} and "-c" in argv:
        inner = argv[argv.index("-c") + 1 :]
        if inner:
            try:
                inner_argv = shlex.split(inner[0])
            except ValueError:
                inner_argv = []
            if inner_argv and Path(inner_argv[0]).name in NO_OP_EXECUTABLES:
                raise WireError(
                    f"--check {check['command']!r} wraps a no-op command; see above."
                )


def resolve_executable(check: dict, worktree: Path) -> None:
    argv0 = check["argv"][0]
    if "/" in argv0:
        candidate = (worktree / argv0).resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return
        raise WireError(
            f"--check {check['command']!r} points at {argv0!r}, which is not an "
            f"executable file in {worktree}"
        )
    if shutil.which(argv0) is None:
        raise WireError(
            f"--check {check['command']!r} starts with {argv0!r}, which is not on "
            "PATH. Wire a command this repo can actually run."
        )


WRAPPER_TEMPLATE = '''#!/usr/bin/env python3
"""Project verifier for land-work's project-verifier gate.

Generated by bento's `wire-land-verifier` skill. Runs this repo's confirmed
gate command(s) and emits the schema_version:1 result that
`land-work-run-verifier.py` expects as its final stdout line.

Edit CHECKS when the repo's real gate changes. Keep the trailing JSON line as
the only thing this script writes to stdout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[{parents}]

CHECKS: list[tuple[str, list[str]]] = {checks}


def main() -> int:
    selected_checks = []
    overall = "passed"
    for name, cmd in CHECKS:
        print(f"==> {{name}}", file=sys.stderr)
        # Route child stdout to stderr so the JSON result stays the only thing
        # this script writes to stdout.
        result = subprocess.run(cmd, cwd=REPO_ROOT, stdout=sys.stderr, stderr=sys.stderr)
        status = "passed" if result.returncode == 0 else "failed"
        if status == "failed":
            overall = "failed"
        selected_checks.append({{"name": name, "status": status}})
    print(json.dumps({{
        "schema_version": 1,
        "status": overall,
        "selected_checks": selected_checks,
    }}))
    return 0 if overall == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def render_wrapper(checks: list[dict], wrapper_rel: Path) -> str:
    rendered = ",\n".join(
        f"    ({json.dumps(c['name'])}, {json.dumps(c['argv'])})" for c in checks
    )
    return WRAPPER_TEMPLATE.format(
        parents=len(wrapper_rel.parts) - 1,
        checks="[\n" + rendered + ",\n]",
    )


def render_manifest(wrapper_rel: Path) -> str:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "command": [f"./{wrapper_rel.as_posix()}"],
                "verified_noop": [],
            },
            indent=2,
        )
        + "\n"
    )


def staging_dir(worktree: Path) -> Path:
    git_dir = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=worktree,
        capture_output=True,
        text=True,
    )
    if git_dir.returncode != 0:
        raise WireError(f"{worktree} is not inside a git worktree")
    return Path(git_dir.stdout.strip()) / STAGING_REL


def draft(worktree: Path, raw_checks: list[str], wrapper_path: str) -> dict:
    wrapper_rel = Path(wrapper_path)
    if wrapper_rel.is_absolute() or ".." in wrapper_rel.parts:
        raise WireError("--wrapper-path must be a relative path inside the worktree")

    checks = [parse_check(raw) for raw in raw_checks]
    for check in checks:
        reject_no_ops(check)
        resolve_executable(check, worktree)

    wrapper_body = render_wrapper(checks, wrapper_rel)
    manifest_body = render_manifest(wrapper_rel)

    staging = staging_dir(worktree)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    (staging / "wrapper").write_text(wrapper_body, encoding="utf-8")
    (staging / "verifier.json").write_text(manifest_body, encoding="utf-8")
    fingerprint = _fingerprint(wrapper_body, manifest_body, wrapper_rel)
    _write_state(
        staging,
        {
            "wrapper_rel": wrapper_rel.as_posix(),
            "fingerprint": fingerprint,
            "checks": [{"name": c["name"], "command": c["command"]} for c in checks],
        },
    )

    return {
        "worktree": str(worktree),
        "checks": [{"name": c["name"], "command": c["command"]} for c in checks],
        "wrapper_target": wrapper_rel.as_posix(),
        "manifest_target": MANIFEST_REL.as_posix(),
        "wrapper_body": wrapper_body,
        "manifest_body": manifest_body,
        "next": "Show both files to the user, then run `validate`, then `apply`.",
    }


def _fingerprint(wrapper_body: str, manifest_body: str, wrapper_rel: Path) -> str:
    digest = hashlib.sha256()
    for part in (wrapper_body, manifest_body, wrapper_rel.as_posix()):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _write_state(staging: Path, state: dict) -> None:
    (staging / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _read_state(worktree: Path) -> tuple[Path, dict]:
    staging = staging_dir(worktree)
    state_path = staging / "state.json"
    if not state_path.is_file():
        raise WireError("no draft found; run `wire-land-verifier.py draft` first")
    return staging, json.loads(state_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------


def _trailing_json(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def validate(worktree: Path, timeout: int) -> tuple[dict, int]:
    staging, state = _read_state(worktree)
    runner = staging / "wrapper"
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)

    # Run from a copy at the real target path so the wrapper's REPO_ROOT
    # (computed from its own depth) resolves the way it will once installed.
    wrapper_rel = Path(state["wrapper_rel"])
    installed = worktree / wrapper_rel
    preexisting = installed.read_bytes() if installed.exists() else None
    installed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runner, installed)
    installed.chmod(installed.stat().st_mode | stat.S_IXUSR)
    try:
        result = subprocess.run(
            [str(installed)],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "schema_valid": False,
            "error": f"verifier did not finish within {timeout}s",
        }, 1
    finally:
        _restore(installed, preexisting)

    parsed = _trailing_json(result.stdout)
    problems: list[str] = []
    if parsed is None:
        problems.append("final stdout line is not a JSON object")
    else:
        if parsed.get("schema_version") != 1:
            problems.append("schema_version must be 1")
        if parsed.get("status") not in {"passed", "failed"}:
            problems.append("status must be 'passed' or 'failed'")
        checks = parsed.get("selected_checks")
        if not isinstance(checks, list) or not checks:
            problems.append(
                "selected_checks must be a nonempty list; a passed verifier with "
                "zero checks is exactly the rubber stamp land-work rejects"
            )
        else:
            expected = [c["name"] for c in state["checks"]]
            actual = [c.get("name") for c in checks if isinstance(c, dict)]
            if actual != expected:
                problems.append(f"selected_checks names {actual} != drafted {expected}")

    schema_valid = not problems
    selected_checks = (parsed or {}).get("selected_checks")
    payload = {
        "worktree": str(worktree),
        "schema_valid": schema_valid,
        "status": (parsed or {}).get("status"),
        "selected_check_count": len(selected_checks) if isinstance(selected_checks, list) else 0,
        "problems": problems,
        "exit_code": result.returncode,
        "stderr_tail": result.stderr[-2000:],
    }

    if schema_valid:
        state["receipt"] = {
            "fingerprint": state["fingerprint"],
            "status": payload["status"],
            "selected_check_count": payload["selected_check_count"],
        }
        _write_state(staging, state)
        payload["next"] = (
            "Draft validated. Run `apply` once the user approves the two files."
            if payload["status"] == "passed"
            else "Schema is valid but the gate is currently red. Confirm with the "
            "user that wiring a failing gate is intended before `apply`."
        )

    # A red-but-schema-valid gate is a legitimate thing to wire, but it is not a
    # silent success: exit nonzero so an agent has to read the report.
    exit_code = 0 if schema_valid and payload["status"] == "passed" else 1
    return payload, exit_code


def _restore(path: Path, preexisting: bytes | None) -> None:
    if preexisting is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(preexisting)


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------


def apply(worktree: Path, force: bool) -> dict:
    staging, state = _read_state(worktree)
    receipt = state.get("receipt")
    if not receipt:
        raise WireError(
            "no validation receipt; run `wire-land-verifier.py validate` before "
            "`apply` so the wrapper is never installed unproven"
        )
    if receipt.get("fingerprint") != state["fingerprint"]:
        raise WireError(
            "the draft changed after validation; re-run `validate` before `apply`"
        )
    if receipt.get("selected_check_count", 0) < 1:
        raise WireError(
            "the validated wrapper reported zero selected checks; refusing to "
            "install a verifier that cannot gate a landing"
        )

    manifest_path = worktree / MANIFEST_REL
    if manifest_path.exists() and not force:
        raise WireError(
            f"{MANIFEST_REL} already exists; re-run with --force to replace it"
        )

    wrapper_path = worktree / Path(state["wrapper_rel"])
    if wrapper_path.exists() and not force:
        raise WireError(
            f"{state['wrapper_rel']} already exists; choose another --wrapper-path "
            "or re-run with --force"
        )

    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staging / "wrapper", wrapper_path)
    wrapper_path.chmod(wrapper_path.stat().st_mode | 0o111)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staging / "verifier.json", manifest_path)

    return {
        "worktree": str(worktree),
        "applied": True,
        "wrapper": state["wrapper_rel"],
        "manifest": MANIFEST_REL.as_posix(),
        "validated_status": receipt.get("status"),
        "next": "Commit both files so land-work finds the manifest on the next landing.",
    }


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worktree", default=".", help="target git worktree (default: cwd)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("discover", help="propose candidate gate commands (writes nothing)")

    draft_parser = subparsers.add_parser("draft", help="stage the wrapper and manifest")
    draft_parser.add_argument(
        "--check",
        action="append",
        required=True,
        metavar="NAME::COMMAND",
        help="a confirmed gate command; repeatable. Bare COMMAND names itself.",
    )
    draft_parser.add_argument(
        "--wrapper-path",
        default=DEFAULT_WRAPPER_REL,
        help=f"repo-relative wrapper path (default: {DEFAULT_WRAPPER_REL})",
    )

    validate_parser = subparsers.add_parser(
        "validate", help="run the staged wrapper and check its output schema"
    )
    validate_parser.add_argument(
        "--timeout", type=int, default=1800, help="seconds before giving up"
    )

    apply_parser = subparsers.add_parser(
        "apply", help="install the validated wrapper and manifest"
    )
    apply_parser.add_argument(
        "--force", action="store_true", help="replace existing wrapper/manifest"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worktree = Path(args.worktree).resolve()
    if not worktree.is_dir():
        print(f"error: {worktree} is not a directory", file=sys.stderr)
        return 2

    try:
        if args.command == "discover":
            payload, exit_code = discover(worktree), 0
        elif args.command == "draft":
            payload, exit_code = draft(worktree, args.check, args.wrapper_path), 0
        elif args.command == "validate":
            payload, exit_code = validate(worktree, args.timeout)
        else:
            payload, exit_code = apply(worktree, args.force), 0
    except WireError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
