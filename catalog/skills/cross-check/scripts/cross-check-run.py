#!/usr/bin/env python3
"""Bento cross-check runner.

Runs the COUNTERPART runtime headlessly and read-only to review an artifact,
then renders the review to /tmp and echoes it. On any failure (nonzero exit,
empty/malformed output, timeout) it signals the caller to use the same-runtime
fallback path. With --render-only it skips execution and just writes a templated
review file from stdin (used by the fallback path). See SKILL.md."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cross_check_common as common  # noqa: E402

# Exit codes with meaning for the calling agent.
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RECURSION_SKIP = 3  # already inside a cross-check; do nothing
EXIT_FALLBACK_REQUIRED = 4  # cross run failed; caller must run same-runtime fallback


def _bundled_prompts_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "references" / "prompts"


def _xdg_config_home() -> Path | None:
    raw = os.environ.get("XDG_CONFIG_HOME")
    return Path(raw) if raw else None


def _read_artifact(artifact: str | None) -> str:
    if artifact is None or artifact == "-":
        return sys.stdin.read()
    return Path(artifact).read_text(encoding="utf-8")


def _repo_root(cwd: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def extract_verdict(current_runtime: str, *, stdout: str, last_message_file: str | None) -> str:
    """Pull the reviewer's final message out of the runtime's output."""
    counterpart = common.counterpart_of(current_runtime)
    if counterpart == "codex":
        if last_message_file and Path(last_message_file).is_file():
            return Path(last_message_file).read_text(encoding="utf-8")
        return stdout
    # claude --output-format json
    try:
        result = json.loads(stdout).get("result", "")
    except (json.JSONDecodeError, AttributeError):
        return ""
    # A null or non-string result must behave like empty output (→ fallback),
    # not crash on .strip() downstream.
    return result if isinstance(result, str) else ""


def run_cross(
    *,
    current_runtime: str,
    artifact_type: str,
    artifact_text: str,
    slug: str,
    model: str | None,
    timeout: int,
    cwd: Path,
    scope: str | None,
    truncated: bool,
    now: datetime,
) -> tuple[int, str]:
    """Execute the counterpart review. Returns (exit_code, message)."""
    if common.recursion_active():
        return EXIT_RECURSION_SKIP, (
            f"cross-check: {common.RECURSION_ENV} set; already inside a "
            f"cross-check. Skipping to avoid recursion."
        )

    repo_root = _repo_root(cwd)
    try:
        prompt_path = common.resolve_prompt(
            artifact_type,
            repo_root=repo_root,
            xdg_config_home=_xdg_config_home(),
            bundled_dir=_bundled_prompts_dir(),
        )
    except (FileNotFoundError, ValueError) as exc:
        return EXIT_USAGE, f"cross-check: {exc}"

    prompt = common.compose_prompt(
        prompt_path.read_text(encoding="utf-8"),
        artifact_text,
        artifact_type=artifact_type,
    )

    counterpart = common.counterpart_of(current_runtime)
    last_file: str | None = None
    tmp_handle = None
    if counterpart == "codex":
        tmp_handle = tempfile.NamedTemporaryFile(
            prefix="cross-check-last-", suffix=".md", delete=False
        )
        tmp_handle.close()
        last_file = tmp_handle.name

    cmd = common.build_counterpart_command(
        current_runtime, model=model, last_message_file=last_file
    )
    child_env = {**os.environ, common.RECURSION_ENV: "1"}

    try:
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(cwd),
                env=child_env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return EXIT_FALLBACK_REQUIRED, (
                f"cross-check: {counterpart} review timed out after {timeout}s; "
                f"use the same-runtime fallback."
            )
        except FileNotFoundError:
            return EXIT_FALLBACK_REQUIRED, (
                f"cross-check: {counterpart} not executable; use the same-runtime fallback."
            )

        if proc.returncode != 0:
            return EXIT_FALLBACK_REQUIRED, (
                f"cross-check: {counterpart} exited {proc.returncode}; use the "
                f"same-runtime fallback.\n{proc.stderr.strip()}"
            )

        verdict = extract_verdict(
            current_runtime, stdout=proc.stdout, last_message_file=last_file
        )
        if not verdict.strip():
            return EXIT_FALLBACK_REQUIRED, (
                f"cross-check: {counterpart} produced no review text; use the "
                f"same-runtime fallback."
            )

        target = _write_review(
            verdict=verdict,
            current_runtime=current_runtime,
            artifact_type=artifact_type,
            mode="cross",
            slug=slug,
            scope=scope,
            truncated=truncated,
            now=now,
        )
        body = target.read_text(encoding="utf-8")
        return EXIT_OK, f"{target}\n\n{body}"
    finally:
        if last_file:
            Path(last_file).unlink(missing_ok=True)


def _write_review(
    *,
    verdict: str,
    current_runtime: str,
    artifact_type: str,
    mode: str,
    slug: str,
    scope: str | None,
    truncated: bool,
    now: datetime,
) -> Path:
    rendered = common.render_review(
        verdict=verdict,
        current_runtime=current_runtime,
        artifact_type=artifact_type,
        mode=mode,
        scope=scope,
        truncated=truncated,
    )
    target = common.output_path(slug=slug, now=now, tmp_root=common.tmp_root())
    target.parent.mkdir(parents=True, exist_ok=True)
    # Same slug within the same second must not clobber a prior review.
    if target.exists():
        n = 2
        while target.with_name(f"{target.stem}-{n}{target.suffix}").exists():
            n += 1
        target = target.with_name(f"{target.stem}-{n}{target.suffix}")
    target.write_text(rendered, encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cross-check-run",
        description="Run a read-only counterpart review and write it to /tmp.",
    )
    parser.add_argument(
        "--current-runtime", required=True, choices=sorted(common.COUNTERPART)
    )
    parser.add_argument(
        "--artifact-type", required=True, choices=list(common.ARTIFACT_TYPES)
    )
    parser.add_argument(
        "--artifact", help="path to the artifact, or '-'/omit for stdin"
    )
    parser.add_argument("--slug", required=True, help="kebab-case output filename slug")
    parser.add_argument("--model", help="override the reviewer model")
    parser.add_argument("--timeout", type=int, default=600, help="seconds (default 600)")
    parser.add_argument("--scope", help="human-readable description of what was reviewed")
    parser.add_argument(
        "--truncated",
        action="store_true",
        help="mark the review as based on a trimmed/partial artifact",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the counterpart command (JSON) without executing",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="skip execution; render a review file from stdin (fallback path)",
    )
    parser.add_argument(
        "--mode",
        choices=["cross", "degraded"],
        default="degraded",
        help="header mode for --render-only (default degraded)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now()

    if args.dry_run:
        cmd = common.build_counterpart_command(
            args.current_runtime, model=args.model, last_message_file="<LAST_MESSAGE_FILE>"
        )
        print(json.dumps({"command": cmd, "counterpart": common.counterpart_of(args.current_runtime)}, indent=2))
        return EXIT_OK

    try:
        content = _read_artifact(args.artifact)
    except OSError as exc:
        print(f"cross-check: cannot read artifact: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.render_only:
        target = _write_review(
            verdict=content,
            current_runtime=args.current_runtime,
            artifact_type=args.artifact_type,
            mode=args.mode,
            slug=args.slug,
            scope=args.scope,
            truncated=args.truncated,
            now=now,
        )
        print(str(target))
        return EXIT_OK

    code, message = run_cross(
        current_runtime=args.current_runtime,
        artifact_type=args.artifact_type,
        artifact_text=content,
        slug=args.slug,
        model=args.model,
        timeout=args.timeout,
        cwd=Path.cwd(),
        scope=args.scope,
        truncated=args.truncated,
        now=now,
    )
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
