#!/usr/bin/env python3
"""SessionStart hook (Codex): agent-env doctor — runtime-agnostic subset.

Detects agent wiring that is silently broken and injects loud, non-blocking
warnings into the session context. This Codex peer runs only the two checks
that are meaningful independent of the Claude runtime:

  1. Every ``@import`` in CLAUDE.md / AGENTS.md / GEMINI.md (followed
     recursively) resolves to a non-empty file. Flags dangling imports,
     empty (0-byte / whitespace-only) imports, and imports blocked by a
     file where a directory is expected.
  4. .agent-mode.local, if present, contains only recognized key=value
     lines; unknown tokens are flagged.

The Claude peer additionally runs check 2 (hook binaries registered in
``.claude/settings.json``) and check 3 (dormant Claude plugins from the
Claude plugin registry). Both are Claude-specific wiring — Codex has neither
``.claude/settings.json`` hook registration nor Claude's plugin manifest — so
they are intentionally omitted here rather than reimplemented against surfaces
Codex does not expose.

The hook never blocks (always exits 0), performs bounded file reads only, and
stays silent on a healthy repo. It acts only inside a git repository, so it
never scans a non-project working directory.

Kept deliberately parallel to the Claude peer
(``catalog/hooks/bento/claude/scripts/agent-env-doctor.py``): the shared check
functions below are byte-identical to that file's. Update both together.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Bounded read: no single file contributes more than this many bytes to a
# check, so a pathological doc can never stall session startup.
MAX_READ_BYTES = 256 * 1024

# Root agent-instruction documents whose @imports are followed recursively.
AGENT_DOC_NAMES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")

# Guard rails for import following.
MAX_IMPORT_DEPTH = 8

# Recognized .agent-mode.local keys. Data-driven so a new opt-out only needs
# an entry here to stop reading as an "unknown token".
RECOGNIZED_AGENT_MODE_KEYS = frozenset(
    {"require_worktree", "hygiene_check", "agent_env_doctor"}
)

# @import tokens: an "@" at line start or after whitespace, then a path token.
_IMPORT_RE = re.compile(r"(?:^|\s)@(\S+)")

# Extensions that mark a post-@ token as a doc import even without an
# existing-directory prefix.
_DOC_IMPORT_EXTENSIONS = frozenset({".md", ".markdown", ".mdc", ".mdx"})

# Fenced code blocks (``` or ~~~) and inline code spans (`...`): @tokens inside
# them are code, not doc imports.
_FENCE_RE = re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$")
_INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")


def _read_text_bounded(path: Path) -> str | None:
    """Read up to MAX_READ_BYTES of a file as text, or None on error."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_READ_BYTES)
    except OSError:
        return None


def repo_root(cwd: str) -> str | None:
    """Git top-level for cwd, or None if cwd is not inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    root = result.stdout.strip()
    return root if result.returncode == 0 and root else None


# --- check 1: imports -------------------------------------------------------


def _strip_code(text: str) -> str:
    """Blank out fenced code blocks and inline code spans so @tokens inside
    them (e.g. `@types/node`) are not mistaken for doc imports."""
    text = _FENCE_RE.sub(" ", text)
    return _INLINE_CODE_RE.sub(" ", text)


def _clean_token(raw: str) -> str:
    """Strip wrapping quotes/backticks and trailing punctuation, looping until
    stable so mixed trailers like ``docs/x.md`,`` fully resolve."""
    tok = raw
    while True:
        stripped = tok.strip("`\"'").rstrip(",);:.")
        if stripped == tok:
            return stripped
        tok = stripped


def _looks_like_import(token: str, target: Path) -> bool:
    """True if a post-@ token names a doc import rather than prose."""
    if Path(token).suffix.lower() in _DOC_IMPORT_EXTENSIONS:
        return True
    if "/" in token:
        try:
            return target.parent.is_dir()
        except OSError:
            return False
    return False


def _extract_imports(text: str) -> list[str]:
    imports = []
    for raw in _IMPORT_RE.findall(_strip_code(text)):
        tok = _clean_token(raw)
        if tok:
            imports.append(tok)
    return imports


def _is_empty_file(path: Path) -> bool:
    try:
        if path.stat().st_size == 0:
            return True
    except OSError:
        return False
    text = _read_text_bounded(path)
    return text is not None and text.strip() == ""


def _blocking_ancestor(target: Path) -> Path | None:
    """Nearest existing ancestor of a non-existent target that is not a
    directory — i.e. a file sitting where a directory must be."""
    for parent in target.parents:
        if parent.exists():
            return parent if not parent.is_dir() else None
    return None


def check_imports(root: Path) -> list[str]:
    warnings: list[str] = []
    visited: set[Path] = set()

    def visit(doc: Path, depth: int) -> None:
        try:
            resolved = doc.resolve()
        except OSError:
            return
        if resolved in visited or depth > MAX_IMPORT_DEPTH:
            return
        visited.add(resolved)
        text = _read_text_bounded(doc)
        if text is None:
            return
        for token in _extract_imports(text):
            expanded = os.path.expanduser(token)
            target = Path(expanded)
            if not target.is_absolute():
                target = doc.parent / target
            if not _looks_like_import(token, target):
                continue
            if target.is_dir():
                continue
            if target.exists():
                if _is_empty_file(target):
                    warnings.append(
                        f"empty @import: {doc.name} references '{token}' but that "
                        f"file is empty — nothing is loaded"
                    )
                    continue
                # Follow nested imports in referenced markdown docs.
                if target.suffix.lower() == ".md":
                    visit(target, depth + 1)
                continue
            blocker = _blocking_ancestor(target)
            if blocker is not None:
                warnings.append(
                    f"broken @import: {doc.name} references '{token}' but "
                    f"'{blocker}' is a file where a directory is expected "
                    f"(removed submodule/dir?) — nothing is loaded"
                )
            else:
                warnings.append(
                    f"dangling @import: {doc.name} references '{token}' but that "
                    f"path does not exist — nothing is loaded"
                )

    for name in AGENT_DOC_NAMES:
        doc = root / name
        if doc.is_file():
            visit(doc, 0)
    return warnings


# --- check 4: .agent-mode.local ---------------------------------------------


def check_agent_mode(root: Path) -> list[str]:
    config = root / ".agent-mode.local"
    text = _read_text_bounded(config)
    if text is None:
        return []
    warnings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            warnings.append(
                f".agent-mode.local: '{stripped}' is not a key=value line — it "
                f"disables nothing but reads like a mode toggle"
            )
            continue
        key = stripped.partition("=")[0].strip()
        if key not in RECOGNIZED_AGENT_MODE_KEYS:
            warnings.append(
                f".agent-mode.local: unknown key '{key}' — it toggles nothing"
            )
    return warnings


# --- orchestration ----------------------------------------------------------


def _suppressed(root: Path) -> bool:
    """True when .agent-mode.local sets agent_env_doctor=false."""
    text = _read_text_bounded(root / ".agent-mode.local")
    if text is None:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "agent_env_doctor" and value.strip() == "false":
            return True
    return False


def collect_warnings(root: Path) -> list[str]:
    warnings: list[str] = []
    warnings.extend(check_imports(root))
    warnings.extend(check_agent_mode(root))
    return warnings


def _project_root(hook_input: dict) -> Path | None:
    """Resolve the git repository root for this session, or None to stay
    silent. Prefers the payload cwd; falls back to the process cwd. Acts only
    inside a git repo, so a non-project working directory is never scanned."""
    cwd = hook_input.get("cwd")
    if not isinstance(cwd, str) or not cwd or not os.path.isdir(cwd):
        try:
            cwd = os.getcwd()
        except OSError:
            return None
    root = repo_root(cwd)
    return Path(root) if root else None


def evaluate(hook_input: dict) -> dict | None:
    """Return a SessionStart additionalContext payload, or None to stay silent."""
    root = _project_root(hook_input)
    if root is None:
        return None

    if _suppressed(root):
        return None

    warnings = collect_warnings(root)
    if not warnings:
        return None

    body = "\n".join(f"  - {w}" for w in warnings)
    context = (
        "agent-env doctor found agent wiring that is silently broken (advisory, "
        "non-blocking):\n"
        f"{body}\n"
        "Each item is a guardrail or instruction that currently does nothing. Fix "
        "the wiring or, to silence this check for this repo, add "
        "'agent_env_doctor=false' to .agent-mode.local."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }


def main() -> int:
    # Guarded end-to-end so no failure path (malformed stdin, a check bug, or a
    # BrokenPipe/OSError while writing) can ever exit nonzero and block the
    # session. Core guarantee: always exit 0.
    try:
        try:
            hook_input = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            hook_input = {}
        if not isinstance(hook_input, dict):
            hook_input = {}
        decision = evaluate(hook_input)
        if decision is not None:
            json.dump(decision, sys.stdout)
            sys.stdout.write("\n")
        sys.stdout.flush()
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except Exception:
            pass
    except Exception:
        # Never block session start.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
