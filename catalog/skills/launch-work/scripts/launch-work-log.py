#!/usr/bin/env python3
"""Launch-work progress-log helper.

The log lives at $GIT_DIR/launch-work/log.md — under the per-worktree git
directory, never inside the working tree. That makes the file structurally
untrackable: no rebase pass, no removal commit, no risk of leaking
chore(launch-work-log) commits onto the integration branch.

A read-only fallback to the legacy <worktree>/.launch-work/log.md path lets
in-flight branches finish without manual migration. Writes always go to the
new location.

See catalog/skills/launch-work/SKILL.md for the runtime contract."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


CHECKPOINTS = (
    "claimed",
    "worktree-ready",
    "deps-installed",
    "red-test-written",
    "tests-green",
    "verification-passed",
    "ready-to-land",
)

LOG_REL_PATH = "launch-work/log.md"
LEGACY_LOG_REL_PATH = ".launch-work/log.md"

HEADER_RE = re.compile(
    r"<!--\s*launch-work-log\s*\n"
    r"last-updated:\s*(?P<last_updated>[^\n]+)\n"
    r"checkpoint:\s*(?P<checkpoint>[^\n]+)\n"
    r"-->",
    re.MULTILINE,
)

SLOT_HEADINGS = {
    "next-action": "## Next action",
    "original-task": "## Original task",
    "branch-and-worktree": "## Branch & worktree",
    "verification-state": "## Verification state",
    "decisions-and-dead-ends": "## Decisions & dead-ends",
    "pending-decisions": "## Pending decisions / blockers",
    "notes": "## Notes",
}


def _bundled_template() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "templates" / "log.md"


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _git_dir(cwd: Path) -> Path:
    """Resolved per-worktree git directory ($GIT_DIR for this worktree)."""
    result = _git(cwd, "rev-parse", "--absolute-git-dir")
    return Path(result.stdout.strip())


def _repo_root(cwd: Path) -> Path:
    return Path(_git(cwd, "rev-parse", "--show-toplevel").stdout.strip())


def _current_branch(cwd: Path) -> str:
    return _git(cwd, "branch", "--show-current").stdout.strip()


def _primary_branch(cwd: Path) -> str:
    """Best-effort primary-branch detection. Falls back to 'main'."""
    result = _git(cwd, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().rsplit("/", 1)[-1]
    for name in ("main", "master"):
        if _git(cwd, "show-ref", "--verify", f"refs/heads/{name}", check=False).returncode == 0:
            return name
    return "main"


def _log_path(cwd: Path) -> Path:
    return _git_dir(cwd) / LOG_REL_PATH


def _legacy_log_path(cwd: Path) -> Path:
    return _repo_root(cwd) / LEGACY_LOG_REL_PATH


def _existing_log_for_read(cwd: Path) -> Path | None:
    primary = _log_path(cwd)
    if primary.is_file():
        return primary
    legacy = _legacy_log_path(cwd)
    if legacy.is_file():
        return legacy
    return None


def _replace_header(body: str, *, checkpoint: str, last_updated: str) -> str:
    new_header = (
        f"<!-- launch-work-log\n"
        f"last-updated: {last_updated}\n"
        f"checkpoint: {checkpoint}\n"
        f"-->"
    )
    if HEADER_RE.search(body):
        return HEADER_RE.sub(new_header, body, count=1)
    return new_header + "\n\n" + body


def _read_input(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    return Path(arg).read_text(encoding="utf-8")


def _replace_slot(body: str, *, slot: str, content: str) -> str:
    heading = SLOT_HEADINGS[slot]
    pattern = re.compile(
        rf"({re.escape(heading)}\n\n)(.*?)(?=\n## |\Z)",
        re.DOTALL,
    )
    if not pattern.search(body):
        raise ValueError(f"slot heading not found in log: {heading}")
    replacement = rf"\g<1>{content.rstrip()}\n\n"
    return pattern.sub(replacement, body, count=1)


def cmd_init(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    branch = _current_branch(cwd)
    primary = _primary_branch(cwd)
    if branch == primary:
        print(
            "launch-work-log: refusing to create a log on the primary branch "
            f"({primary}); switch to a feature branch first.",
            file=sys.stderr,
        )
        return 2

    log_path = _log_path(cwd)
    if log_path.exists():
        print(
            f"launch-work-log: {log_path} already exists; use 'update' instead.",
            file=sys.stderr,
        )
        return 2

    template = _bundled_template().read_text(encoding="utf-8")
    body = _replace_header(template, checkpoint="worktree-ready", last_updated=_now_iso_utc())
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(body, encoding="utf-8")

    print(json.dumps({"path": str(log_path), "checkpoint": "worktree-ready"}))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    if args.checkpoint not in CHECKPOINTS:
        print(
            f"launch-work-log: unknown checkpoint: {args.checkpoint}; "
            f"valid: {', '.join(CHECKPOINTS)}",
            file=sys.stderr,
        )
        return 2
    cwd = Path.cwd().resolve()
    log_path = _log_path(cwd)
    if not log_path.is_file():
        legacy = _legacy_log_path(cwd)
        if legacy.is_file():
            print(
                f"launch-work-log: log found at legacy path {legacy}; "
                "remove it (e.g. via land-work-clean-log) and run 'init' to "
                "create the new $GIT_DIR-based log before further updates.",
                file=sys.stderr,
            )
            return 2
        print(
            f"launch-work-log: {log_path} not found; run 'init' first.",
            file=sys.stderr,
        )
        return 2

    body = log_path.read_text(encoding="utf-8")
    if args.slot is not None:
        if args.slot not in SLOT_HEADINGS:
            print(
                f"launch-work-log: unknown slot: {args.slot}; "
                f"valid: {', '.join(SLOT_HEADINGS)}",
                file=sys.stderr,
            )
            return 2
        if args.content is None:
            print("launch-work-log: --slot requires --content", file=sys.stderr)
            return 2
        body = _replace_slot(body, slot=args.slot, content=_read_input(args.content))

    body = _replace_header(body, checkpoint=args.checkpoint, last_updated=_now_iso_utc())
    log_path.write_text(body, encoding="utf-8")

    print(json.dumps({"path": str(log_path), "checkpoint": args.checkpoint}))
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    log_path = _existing_log_for_read(cwd)
    if log_path is None:
        print(f"launch-work-log: log not found under $GIT_DIR or legacy path.", file=sys.stderr)
        return 2

    body = log_path.read_text(encoding="utf-8")
    match = HEADER_RE.search(body)
    if not match:
        print("launch-work-log: log file is missing the expected header.", file=sys.stderr)
        return 2

    payload = {
        "path": str(log_path),
        "last_updated": match.group("last_updated").strip(),
        "checkpoint": match.group("checkpoint").strip(),
    }
    print(json.dumps(payload))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="launch-work-log")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the initial log file under $GIT_DIR/launch-work/log.md")

    update = sub.add_parser("update", help="rewrite the log header in place")
    update.add_argument("--checkpoint", required=True)
    update.add_argument("--slot", default=None)
    update.add_argument(
        "--content",
        default=None,
        help="path to slot content file or '-' for stdin",
    )

    sub.add_parser("read", help="emit log header as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "update":
        return cmd_update(args)
    if args.cmd == "read":
        return cmd_read(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
