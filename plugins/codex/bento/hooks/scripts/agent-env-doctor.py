#!/usr/bin/env python3
"""SessionStart hook (Codex): agent-env doctor — runtime-agnostic subset.

Detects agent wiring that is silently broken and injects loud, non-blocking
warnings into the session context. This Codex peer runs the checks that are
meaningful independent of the Claude runtime:

  1. Every ``@import`` in CLAUDE.md / AGENTS.md / GEMINI.md (followed
     recursively) resolves to a non-empty file. Flags dangling imports,
     empty (0-byte / whitespace-only) imports, and imports blocked by a
     file where a directory is expected.
  4. .agent-mode.local, if present, contains only recognized key=value
     lines; unknown tokens are flagged.
  5. This checkout's .git/config has core.bare = true while the checkout
     still has a working tree.
  6. `git worktree prune --dry-run` reports prunable worktrees.
  7. Stale /tmp/land-work-preview-* directories and directories under
     ~/.local/share/worktrees/<repo>/ that are not registered git worktrees.
  8. When .beads/ exists: an orphan dolt sql-server process holding the
     beads DB lock while .beads/dolt-server.port is absent.

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
import time
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
    {
        "require_worktree",
        "hygiene_check",
        "agent_env_doctor",
        "agent_env_doctor_skip_plugin",
        "agent_env_doctor_preview_max_age_hours",
    }
)

# Default staleness threshold for /tmp/land-work-preview-* directories.
DEFAULT_PREVIEW_MAX_AGE_HOURS = 24.0

# .agent-mode.local also carries syntax owned by dotfiles' agent-mode launcher
# (bashrc.agent-mode.sh), not by Bento: a bare "dangerous" token, a quoted
# `mode = "..."` assignment, and an optional `tools = ...` assignment. These
# are recognized as valid launcher grammar regardless of the quoted value —
# the launcher itself decides whether a given mode/tool activates anything —
# so Bento must not flag them as unknown. The tools line is matched exactly as
# permissively as the launcher's own parser: any line whose key is `tools`
# followed by `=` is recognized, with no requirement on bracket/comma
# strictness, since the launcher itself only greps for quoted tokens anywhere
# on that line (`_agent_mode_tools_line` / `_agent_mode_tool_enabled` in
# bashrc.agent-mode.sh) — so `tools = ["claude" "codex"]` (missing comma) or a
# trailing comma are both real, effective launcher config, not malformed
# input. Anything that doesn't match this grammar or Bento's own key=value
# keys still warns.
_LAUNCHER_DANGEROUS_TOKEN = "dangerous"
_LAUNCHER_MODE_RE = re.compile(r'^mode\s*=\s*"[^"]+"\s*$')
_LAUNCHER_TOOLS_RE = re.compile(r"^tools\s*=")

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


def _read_agent_mode_text(path: Path) -> str | None:
    """Read .agent-mode.local without universal-newline translation, so a
    CRLF-terminated line is preserved exactly as bash's `IFS= read -r line`
    sees it: only the trailing "\\n" is a separator, and a stray "\\r" stays
    part of the line. Python's default text mode would silently translate
    "\\r\\n" to "\\n", making a broken CRLF "dangerous\\r\\n" line compare
    equal to the bare "dangerous" token even though the real launcher's exact
    `case` match does not activate on it."""
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
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
    text = _read_agent_mode_text(config)
    if text is None:
        return []
    warnings: list[str] = []
    # Split only on "\n", matching bash's `IFS= read -r line` line boundary
    # (str.splitlines() would additionally split on a bare "\r", which bash
    # does not treat as a line terminator here).
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # The launcher's bash `case "$line" in "dangerous")` matches the raw
        # line from `IFS= read -r line` with zero whitespace tolerance — a
        # leading/trailing-space-padded "dangerous " does NOT activate it, so
        # this comparison must use the unstripped line, not `stripped`.
        if line == _LAUNCHER_DANGEROUS_TOKEN:
            continue
        if _LAUNCHER_MODE_RE.match(stripped) or _LAUNCHER_TOOLS_RE.match(stripped):
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


# --- check 5: bare primary checkout with a working tree ---------------------


_INI_SECTION_RE = re.compile(r"^\[([^\]]+)\]")
_CORE_BARE_TRUE_RE = re.compile(r"(?i)^bare\s*=\s*true$")


def _core_bare_true(config_text: str) -> bool:
    """True when config_text sets ``bare = true`` inside its ``[core]``
    section specifically — not merely anywhere in the file, since another
    section (e.g. a submodule's) could coincidentally define a same-named
    key without that meaning core.bare is set."""
    section: str | None = None
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        header = _INI_SECTION_RE.match(stripped)
        if header:
            section = header.group(1).strip().lower()
            continue
        if section == "core" and _CORE_BARE_TRUE_RE.match(stripped):
            return True
    return False


def check_bare_primary(root: Path) -> list[str]:
    """Warn when .git/config sets core.bare = true but this checkout still
    has a working tree — a corrupted primary checkout where every git
    command fails with "fatal: this operation must be run in a work tree"."""
    git_dir = root / ".git"
    if not git_dir.is_dir():
        # A file (not a directory) means this is a linked worktree's
        # gitdir pointer, not the primary checkout; nothing to check here.
        return []
    config_text = _read_text_bounded(git_dir / "config")
    if config_text is None or not _core_bare_true(config_text):
        return []
    try:
        has_working_tree_files = any(p.name != ".git" for p in root.iterdir())
    except OSError:
        has_working_tree_files = False
    if not has_working_tree_files:
        return []
    return [
        "bare primary checkout: .git/config sets core.bare = true but this "
        "checkout has files — git commands here fail with \"fatal: this "
        "operation must be run in a work tree\""
    ]


# --- checks 6/7: worktree bookkeeping (one shared `git worktree list` call) --


def _worktree_list_entries(root: Path) -> list[dict]:
    """Parse `git worktree list --porcelain` once into per-worktree records
    (path, and a "prunable" reason when git's own bookkeeping flags one) so
    checks 6 and 7 both answer from a single subprocess call instead of each
    forking git separately for overlapping information."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        # Not a git repository (or git otherwise failed) — nothing to judge.
        return []
    entries: list[dict] = []
    current: dict | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current = {"path": line[len("worktree "):], "prunable": None}
            entries.append(current)
        elif line.startswith("prunable") and current is not None:
            reason = line[len("prunable"):].strip(" :")
            current["prunable"] = reason or "stale worktree"
    return entries


# --- check 6: prunable git worktrees -----------------------------------------


def check_prunable_worktrees(root: Path, entries: list[dict] | None = None) -> list[str]:
    if entries is None:
        entries = _worktree_list_entries(root)
    lines = [
        f"{entry['path']}: {entry['prunable']}"
        for entry in entries
        if entry.get("prunable")
    ]
    if not lines:
        return []
    return [
        f"prunable git worktree(s): {'; '.join(lines)} — run "
        "'git worktree prune' to clean them up"
    ]


# --- check 7: stale previews and orphan worktree directories ----------------


def _preview_max_age_hours(root: Path) -> float:
    text = _read_text_bounded(root / ".agent-mode.local")
    if text is None:
        return DEFAULT_PREVIEW_MAX_AGE_HOURS
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "agent_env_doctor_preview_max_age_hours":
            try:
                return float(value.strip())
            except ValueError:
                continue
    return DEFAULT_PREVIEW_MAX_AGE_HOURS


def check_stale_previews(root: Path, tmp_root: Path, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    max_age_seconds = _preview_max_age_hours(root) * 3600
    warnings: list[str] = []
    try:
        entries = sorted(tmp_root.glob("land-work-preview-*"))
    except OSError:
        entries = []
    for entry in entries:
        try:
            age_seconds = now - entry.stat().st_mtime
        except OSError:
            continue
        if age_seconds >= max_age_seconds:
            warnings.append(
                f"stale land-work preview: {entry} is "
                f"{age_seconds / 3600:.1f}h old (> {max_age_seconds / 3600:.0f}h) "
                "— remove it or let closure clean it up"
            )
    return warnings


def _repo_name(root: Path) -> str | None:
    """Project name for the worktree root, stable across every linked
    worktree of the same repo (derived from the primary checkout that the
    shared .git dir lives under, not from whichever worktree is running)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    common_dir = result.stdout.strip()
    if not common_dir:
        return None
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = root / common_path
    try:
        return common_path.resolve().parent.name
    except OSError:
        return None


def _registered_worktree_paths(entries: list[dict]) -> set[Path]:
    paths: set[Path] = set()
    for entry in entries:
        candidate = Path(entry["path"])
        try:
            paths.add(candidate.resolve())
        except OSError:
            paths.add(candidate)
    return paths


def check_worktree_root_orphans(
    root: Path, home: Path, entries: list[dict] | None = None
) -> list[str]:
    repo_name = _repo_name(root)
    if not repo_name:
        return []
    worktrees_dir = home / ".local" / "share" / "worktrees" / repo_name
    if not worktrees_dir.is_dir():
        return []
    if entries is None:
        entries = _worktree_list_entries(root)
    registered = _registered_worktree_paths(entries)
    warnings: list[str] = []
    try:
        entries = sorted(worktrees_dir.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            resolved = entry.resolve()
        except OSError:
            resolved = entry
        if resolved in registered:
            continue
        warnings.append(
            f"orphan worktree directory: {entry} is not a registered git "
            "worktree — dead directory left behind, safe to remove"
        )
    return warnings


# --- check 8: orphan dolt sql-server ------------------------------------------


def check_orphan_dolt_server(root: Path) -> list[str]:
    beads_dir = root / ".beads"
    if not beads_dir.is_dir():
        return []
    if (beads_dir / "dolt-server.port").exists():
        return []
    dolt_dir = str(beads_dir / "dolt")
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,args"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    warnings: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, args = parts
        if "dolt" not in args or "sql-server" not in args:
            continue
        # Path-boundary match: dolt_dir must appear as a whole path token,
        # not merely as a string prefix (a sibling directory like
        # "<dolt_dir>-staging" must not match).
        matched = bool(
            re.search(rf"(?:^|[\s\"'=]){re.escape(dolt_dir)}(?:$|[\s\"'/])", args)
        )
        if not matched and sys.platform.startswith("linux"):
            try:
                cwd = os.readlink(f"/proc/{pid_str}/cwd")
            except OSError:
                cwd = None
            if cwd is not None and (
                cwd == str(root) or cwd == str(beads_dir) or cwd.startswith(str(beads_dir) + os.sep)
            ):
                matched = True
        if matched:
            warnings.append(
                f"orphan dolt sql-server: PID {pid_str} references this "
                "repo's .beads/dolt but .beads/dolt-server.port is absent "
                "— bd calls will hang until it is killed or the port file "
                "is restored"
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


def collect_warnings(
    root: Path, home: Path, tmp_root: Path, now: float | None = None
) -> list[str]:
    warnings: list[str] = []
    warnings.extend(check_imports(root))
    warnings.extend(check_agent_mode(root))
    warnings.extend(check_bare_primary(root))
    worktree_entries = _worktree_list_entries(root)
    warnings.extend(check_prunable_worktrees(root, entries=worktree_entries))
    warnings.extend(check_stale_previews(root, tmp_root, now=now))
    warnings.extend(check_worktree_root_orphans(root, home, entries=worktree_entries))
    warnings.extend(check_orphan_dolt_server(root))
    return warnings


def _project_root(hook_input: dict) -> Path | None:
    """Resolve the git repository root for this session, or None to stay
    silent. Prefers the payload cwd; falls back to the process cwd. Acts only
    inside a git repo, so a non-project working directory is never scanned."""
    cwd = hook_input.get("cwd")
    if not isinstance(cwd, str) or not cwd or not os.path.isdir(cwd):
        try:
            # hook-cwd-exempt: last-resort fallback only when the payload lacks a
            # usable `cwd` (hook_input["cwd"] is the primary source above).
            cwd = os.getcwd()
        except OSError:
            return None
    root = repo_root(cwd)
    if root:
        return Path(root)
    # `git rev-parse --show-toplevel` itself fails once core.bare is flipped
    # true on a checkout that still has a working tree — exactly the
    # condition check_bare_primary exists to catch. Fall back to cwd only for
    # that specific condition (a real .git dir whose config actually sets
    # core.bare = true), not for every rev-parse failure — an unrelated
    # refusal (e.g. "detected dubious ownership") must still stay silent per
    # the "never scan a non-project directory" contract.
    git_dir = Path(cwd) / ".git"
    if git_dir.is_dir():
        config_text = _read_text_bounded(git_dir / "config")
        if config_text is not None and _core_bare_true(config_text):
            return Path(cwd)
    return None


def evaluate(
    hook_input: dict,
    home: Path | None = None,
    tmp_root: Path | None = None,
    now: float | None = None,
) -> dict | None:
    """Return a SessionStart additionalContext payload, or None to stay silent."""
    root = _project_root(hook_input)
    if root is None:
        return None

    if _suppressed(root):
        return None

    resolved_home = home or Path(os.environ.get("HOME", str(Path.home())))
    resolved_tmp_root = tmp_root if tmp_root is not None else Path("/tmp")

    warnings = collect_warnings(root, resolved_home, resolved_tmp_root, now=now)
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
