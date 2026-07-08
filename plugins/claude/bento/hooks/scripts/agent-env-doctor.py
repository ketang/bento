#!/usr/bin/env python3
"""SessionStart hook: agent-env doctor.

Detects agent wiring that is silently broken — the failure class where a
guardrail is advertised but no-ops with zero signal — and injects loud,
non-blocking warnings into the session context. Four checks:

  1. Every ``@import`` in CLAUDE.md / AGENTS.md / GEMINI.md (followed
     recursively) resolves to a non-empty file. Flags dangling imports,
     empty (0-byte / whitespace-only) imports, and imports blocked by a
     file where a directory is expected (e.g. a submodule dir removed and
     replaced by a stray file).
  2. Every hook command registered in the project's .claude/settings.json
     resolves to an existing executable, and any wrapper script that gates
     on an absent external binary (so it silently exits 0) is flagged.
  3. Installed plugins whose hard-trigger precondition is unmet get an
     "installed but dormant" nudge, driven by a data table so new plugins
     register their own precondition.
  4. .agent-mode.local, if present, contains only recognized key=value
     lines; unknown tokens are flagged.

The hook never blocks (always exits 0) and never emits a hard decision. It
performs bounded file reads only and stays silent on a healthy repo.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
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

# Plugins that install guardrails gated behind a repo-local precondition. When
# the plugin is installed but its precondition file/dir is absent, the plugin
# is dormant: its skills never trigger. Data-driven so a new plugin registers
# by appending one record — no per-plugin branching below.
#   kind: "dir" | "file" — what "path" is expected to be
#   path: repo-relative path that must exist for the plugin to be live
#   activate: imperative remediation shown to the agent
PLUGIN_PRECONDITIONS = (
    {
        "plugin": "storystore",
        "kind": "dir",
        "path": "docs/stories",
        "activate": "run the storystore stories-init skill to create docs/stories/",
    },
    {
        "plugin": "bugshot",
        "kind": "file",
        "path": ".agent-plugins/bento/bugshot/viz/capture-command",
        "activate": "run the bugshot wire-bugshot skill to create its capture-command",
    },
)

# @import tokens: an "@" at line start or after whitespace, then a path token.
# The leading (?:^|\s) excludes email addresses (foo@bar.com) and inline "@"
# uses where "@" abuts preceding text.
_IMPORT_RE = re.compile(r"(?:^|\s)@(\S+)")

# Extensions that mark a post-@ token as a doc import even without an
# existing-directory prefix. Kept narrow so prose like "@app.route" is not
# treated as a dangling import.
_DOC_IMPORT_EXTENSIONS = frozenset({".md", ".markdown", ".mdc", ".mdx"})

# Fenced code blocks (``` or ~~~) and inline code spans (`...`): @tokens inside
# them are code, not doc imports (e.g. `@types/node`, `@app.route("/x")`).
_FENCE_RE = re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$")
_INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")

# Command-position binary gating inside wrapper scripts: `command -v X`,
# `which X`, `hash X`, `type X`. Anchored to the start of a shell command
# segment (optionally after a control keyword and/or `!`) so prose and flags
# like `find . -type f` or a `# which formatter` comment never match.
_GATE_RE = re.compile(
    r"""^\s*(?:(?:if|elif|while|until|then|else|do)\s+)?!?\s*
        (?:command\s+-v|which|hash|type)\s+
        ["']?([A-Za-z0-9_.\-/]+)""",
    re.VERBOSE,
)

# Split a shell line into command segments on the separators that begin a new
# simple command, so gating is judged at each segment's start.
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;&|()]")

# Leading VAR=value environment-assignment prefix (e.g. `FOO=1 my-hook.sh`).
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Shell keywords/builtins that are never external binaries. When a hook
# command's effective first word is one of these, it cannot be judged as a
# missing binary, so it is skipped.
_SHELL_BUILTINS = frozenset(
    {
        "if", "then", "else", "elif", "fi", "for", "while", "until", "do",
        "done", "case", "esac", "exec", "eval", "source", ".", "[", "[[",
        "test", "true", "false", ":", "cd", "export", "unset", "set",
        "command", "builtin", "return", "exit", "read", "echo", "printf",
    }
)


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
    """True if a post-@ token names a doc import rather than prose. A token
    qualifies when it has a doc extension, or contains a path separator and
    resolves under an existing directory. Bare words (``@dangerous``) and
    package specs without a real directory prefix (``@types/node``) do not."""
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
    directory — i.e. a file sitting where a directory must be (the
    removed-submodule-left-a-stray-file case)."""
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


# --- check 2: hook binaries -------------------------------------------------


def _expand_vars(value: str, env: dict) -> str | None:
    """Expand ${VAR} and $VAR from env. Returns None if any referenced
    variable is undefined (command cannot be judged, so skip it)."""
    undefined = False

    def repl(match: re.Match) -> str:
        nonlocal undefined
        name = match.group(1) or match.group(2)
        if name not in env:
            undefined = True
            return ""
        return env[name]

    expanded = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", repl, value)
    return None if undefined else expanded


def _iter_hook_commands(settings: dict) -> list[str]:
    commands: list[str] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return commands
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []) if isinstance(entry.get("hooks"), list) else []:
                if isinstance(hook, dict) and hook.get("type") == "command":
                    command = hook.get("command")
                    if isinstance(command, str) and command.strip():
                        commands.append(command)
    return commands


def _gated_binaries(script: Path) -> list[str]:
    """External binaries a wrapper script gates its behavior on."""
    text = _read_text_bounded(script)
    if text is None:
        return []
    seen: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for segment in _SEGMENT_SPLIT_RE.split(line):
            match = _GATE_RE.match(segment)
            if match is None:
                continue
            name = match.group(1)
            # Skip path-y self references and shell builtins commonly probed.
            if "/" in name or name in seen or name in {"-v", "command"}:
                continue
            seen.append(name)
    return seen


def check_hook_binaries(root: Path, env: dict) -> list[str]:
    warnings: list[str] = []
    path_env = env.get("PATH")
    for name in ("settings.json", "settings.local.json"):
        settings_file = root / ".claude" / name
        if not settings_file.is_file():
            continue
        text = _read_text_bounded(settings_file)
        if text is None:
            continue
        try:
            settings = json.loads(text)
        except json.JSONDecodeError:
            warnings.append(
                f"unreadable hook config: .claude/{name} is not valid JSON — its "
                f"hooks may not be registered"
            )
            continue
        if not isinstance(settings, dict):
            continue
        for command in _iter_hook_commands(settings):
            # Commands that reference ${CLAUDE_PLUGIN_ROOT} belong to some
            # plugin; from the project root we cannot know which. When the
            # doctor itself runs as a plugin hook that variable is set to
            # bento's own root, so expanding it here would judge another
            # plugin's command against the wrong tree. Skip entirely.
            if "CLAUDE_PLUGIN_ROOT" in command:
                continue
            try:
                words = shlex.split(command)
            except ValueError:
                words = command.split()
            # Skip leading VAR=value environment-assignment prefixes.
            idx = 0
            while idx < len(words) and _ENV_ASSIGN_RE.match(words[idx]):
                idx += 1
            if idx >= len(words):
                continue
            first = words[idx]
            # A shell builtin/keyword as the effective command is never a
            # missing external binary, so it cannot be judged here.
            if first in _SHELL_BUILTINS:
                continue
            resolved = _expand_vars(first, env)
            if resolved is None:
                # Contains an unset variable; cannot judge from here, so skip
                # rather than false-flag.
                continue
            if not resolved:
                continue
            if "/" in resolved:
                script = Path(os.path.expanduser(resolved))
                if not script.is_absolute():
                    script = root / script
                if not script.exists():
                    warnings.append(
                        f"registered hook command not found: '{resolved}' "
                        f"(from .claude/{name}) — the hook silently does nothing"
                    )
                    continue
                for binary in _gated_binaries(script):
                    if shutil.which(binary, path=path_env) is None:
                        warnings.append(
                            f"inert hook: '{resolved}' gates on missing binary "
                            f"'{binary}' — it exits 0 without doing anything"
                        )
            else:
                if shutil.which(resolved, path=path_env) is None:
                    warnings.append(
                        f"registered hook command not on PATH: '{resolved}' "
                        f"(from .claude/{name}) — the hook silently does nothing"
                    )
    return warnings


# --- check 3: dormant plugins -----------------------------------------------


def installed_plugins(plugins_file: Path) -> set[str]:
    """Plugin names from installed_plugins.json (keys are ``plugin@marketplace``)."""
    text = _read_text_bounded(plugins_file)
    if text is None:
        return set()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return set()
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return set()
    return {key.split("@", 1)[0] for key in plugins if isinstance(key, str) and key}


def check_dormant_plugins(root: Path, installed: set[str]) -> list[str]:
    warnings: list[str] = []
    for precond in PLUGIN_PRECONDITIONS:
        if precond["plugin"] not in installed:
            continue
        target = root / precond["path"]
        present = target.is_dir() if precond["kind"] == "dir" else target.is_file()
        if not present:
            warnings.append(
                f"{precond['plugin']} is installed but dormant — {precond['path']} "
                f"is missing; {precond['activate']}"
            )
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


def collect_warnings(root: Path, env: dict, plugins_file: Path) -> list[str]:
    warnings: list[str] = []
    warnings.extend(check_imports(root))
    warnings.extend(check_hook_binaries(root, env))
    warnings.extend(check_dormant_plugins(root, installed_plugins(plugins_file)))
    warnings.extend(check_agent_mode(root))
    return warnings


def _plugins_file(home: Path, env: dict) -> Path:
    return home / ".claude" / "plugins" / "installed_plugins.json"


def evaluate(
    hook_input: dict,
    home: Path | None = None,
    env: dict | None = None,
    plugins_file: Path | None = None,
) -> dict | None:
    """Return a SessionStart additionalContext payload, or None to stay silent."""
    environ = os.environ if env is None else env
    resolved_home = home or Path(environ.get("HOME", str(Path.home())))

    cwd = hook_input.get("cwd") or ""
    if not cwd or not os.path.isdir(cwd):
        return None
    root = Path(repo_root(cwd) or cwd)

    if _suppressed(root):
        return None

    pfile = plugins_file if plugins_file is not None else _plugins_file(resolved_home, environ)
    warnings = collect_warnings(root, environ, pfile)
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
    # The whole body — including output emission and the final flush — is
    # guarded so no failure path (malformed stdin, a check bug, or a
    # BrokenPipe/OSError while writing) can ever exit nonzero and block the
    # session. This hook's core guarantee is: always exit 0.
    try:
        hook_input = json.load(sys.stdin)
        decision = evaluate(hook_input)
        if decision is not None:
            json.dump(decision, sys.stdout)
            sys.stdout.write("\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Downstream closed the pipe. Redirect stdout to devnull so the
        # interpreter's shutdown flush cannot re-raise and force a nonzero
        # exit.
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
