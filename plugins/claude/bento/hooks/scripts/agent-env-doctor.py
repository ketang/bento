#!/usr/bin/env python3
"""SessionStart hook: agent-env doctor.

Detects agent wiring that is silently broken — the failure class where a
guardrail is advertised but no-ops with zero signal — and injects loud,
non-blocking warnings into the session context. Checks:

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
     register their own precondition. A repo can mark specific plugins as
     inapplicable via 'agent_env_doctor_skip_plugin' without disabling any
     other check.
  4. .agent-mode.local, if present, contains only recognized key=value
     lines; unknown tokens are flagged.
  5. This checkout's .git/config has core.bare = true while the checkout
     still has a working tree (a corrupted primary checkout where every git
     command fails with "not a work tree").
  6. `git worktree prune --dry-run` reports prunable worktrees.
  7. Stale /tmp/land-work-preview-* directories (older than
     agent_env_doctor_preview_max_age_hours, default 24h) and directories
     under ~/.local/share/worktrees/<repo>/ that are not registered git
     worktrees.
  8. When .beads/ exists: a dolt sql-server process that references this
     repo's .beads/dolt while .beads/dolt-server.port is absent (an orphaned
     server holding the beads DB lock after its port file was lost).

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
import time
from datetime import date
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
        "agent_env_doctor_seen",
        "agent_env_doctor_remind_after",
        "agent_env_doctor_superpowers_pointer_seen",
    }
)

# Installed-plugin name whose presence triggers the one-time superpowers
# coexistence pointer (bento-rdtn.10).
SUPERPOWERS_PLUGIN_NAME = "superpowers"

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


def _dormant_plugin_decisions(
    root: Path,
    installed: set[str],
    skip: frozenset[str],
    seen: frozenset[str],
    remind_after: dict[str, str],
    today: date,
) -> list[dict]:
    """One decision per dormant, non-skipped installed plugin: whether to
    show the full first-sighting nudge (display="full"), the collapsed
    one-liner (display="short"), or nothing at all (fully suppressed by a
    future remind_after date — simply absent from the returned list).

    An unparseable remind_after date fails safe toward re-showing the full
    nudge (treated as already expired) rather than silently suppressing it
    forever.
    """
    decisions: list[dict] = []
    for precond in PLUGIN_PRECONDITIONS:
        plugin = precond["plugin"]
        if plugin not in installed or plugin in skip:
            continue
        target = root / precond["path"]
        present = target.is_dir() if precond["kind"] == "dir" else target.is_file()
        if present:
            continue

        remind_date_str = remind_after.get(plugin)
        if remind_date_str:
            try:
                remind_date = date.fromisoformat(remind_date_str)
            except ValueError:
                remind_date = None
            if remind_date is not None and today < remind_date:
                continue
            display = "full"
        elif plugin in seen:
            display = "short"
        else:
            display = "full"

        decisions.append(
            {
                "plugin": plugin,
                "path": precond["path"],
                "activate": precond["activate"],
                "display": display,
            }
        )
    return decisions


def _format_dormant_plugin_warning(decision: dict) -> str:
    plugin = decision["plugin"]
    if decision["display"] == "short":
        return f"{plugin} dormant — decision pending, see .agent-mode.local"
    return (
        f"{plugin} is installed but dormant — {decision['path']} is missing; "
        f"{decision['activate']}. Options (edit .agent-mode.local): wire it "
        f"now ({decision['activate']}); skip permanently — "
        f"agent_env_doctor_skip_plugin={plugin}; remind later — "
        f"agent_env_doctor_remind_after={plugin}:<YYYY-MM-DD>"
    )


def check_dormant_plugins(
    root: Path,
    installed: set[str],
    skip: frozenset[str] = frozenset(),
    seen: frozenset[str] = frozenset(),
    remind_after: dict[str, str] | None = None,
    today: date | None = None,
) -> list[str]:
    resolved_today = today if today is not None else date.today()
    decisions = _dormant_plugin_decisions(
        root, installed, skip, seen, remind_after or {}, resolved_today
    )
    return [_format_dormant_plugin_warning(d) for d in decisions]


# --- check 3b: superpowers coexistence pointer (bento-rdtn.10) --------------


def check_superpowers_coexistence(installed: set[str], seen: bool) -> list[str]:
    """One-time pointer (never repeated once shown) toward the coexistence
    doc when Anthropic's superpowers plugin is also installed: bento's
    launch-work/land-work supersede superpowers' worktree/finishing skills
    at their hard-trigger boundary, and superpowers' process skills stay in
    force between those two points."""
    if seen or SUPERPOWERS_PLUGIN_NAME not in installed:
        return []
    return [
        "superpowers is also installed — bento's launch-work replaces "
        "superpowers:using-git-worktrees and land-work replaces "
        "superpowers:finishing-a-development-branch; superpowers' process "
        "skills (brainstorming, TDD, systematic-debugging, etc.) remain in "
        "force between those two points. See docs/installing-plugins.md "
        "(\"Coexistence with superpowers\"). This notice prints once per "
        "repo."
    ]


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
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key not in RECOGNIZED_AGENT_MODE_KEYS:
            warnings.append(
                f".agent-mode.local: unknown key '{key}' — it toggles nothing"
            )
            continue
        if key == "agent_env_doctor_skip_plugin":
            known_plugins = {precond["plugin"] for precond in PLUGIN_PRECONDITIONS}
            for name in (n.strip() for n in value.split(",")):
                if name and name not in known_plugins:
                    warnings.append(
                        f".agent-mode.local: unknown plugin '{name}' in "
                        f"agent_env_doctor_skip_plugin — it toggles nothing"
                    )
        elif key == "agent_env_doctor_seen":
            known_plugins = {precond["plugin"] for precond in PLUGIN_PRECONDITIONS}
            for name in (n.strip() for n in value.split(",")):
                if name and name not in known_plugins:
                    warnings.append(
                        f".agent-mode.local: unknown plugin '{name}' in "
                        f"agent_env_doctor_seen — it toggles nothing"
                    )
        elif key == "agent_env_doctor_remind_after":
            known_plugins = {precond["plugin"] for precond in PLUGIN_PRECONDITIONS}
            for entry in (e.strip() for e in value.split(",")):
                if not entry:
                    continue
                if ":" not in entry:
                    warnings.append(
                        f".agent-mode.local: '{entry}' in "
                        "agent_env_doctor_remind_after is not <plugin>:<date> — it "
                        "toggles nothing"
                    )
                    continue
                name, _, date_str = entry.partition(":")
                name = name.strip()
                date_str = date_str.strip()
                if name and name not in known_plugins:
                    warnings.append(
                        f".agent-mode.local: unknown plugin '{name}' in "
                        f"agent_env_doctor_remind_after — it toggles nothing"
                    )
                    continue
                try:
                    date.fromisoformat(date_str)
                except ValueError:
                    warnings.append(
                        f".agent-mode.local: '{date_str}' in "
                        f"agent_env_doctor_remind_after={name}:{date_str} is not a "
                        "YYYY-MM-DD date — it toggles nothing"
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


def _skipped_plugins(root: Path) -> frozenset[str]:
    """Plugin names named in .agent-mode.local's agent_env_doctor_skip_plugin,
    a comma-separated allow-list scoped to the dormant-plugin check only —
    unlike agent_env_doctor=false, every other check still runs."""
    text = _read_text_bounded(root / ".agent-mode.local")
    if text is None:
        return frozenset()
    skipped: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() != "agent_env_doctor_skip_plugin":
            continue
        skipped.update(name.strip() for name in value.split(",") if name.strip())
    return frozenset(skipped)


def _seen_plugins(root: Path) -> frozenset[str]:
    """Plugin names in .agent-mode.local's agent_env_doctor_seen — plugins
    that have already shown the full first-sighting dormancy nudge at least
    once, so subsequent sessions collapse it to a one-line reminder."""
    text = _read_text_bounded(root / ".agent-mode.local")
    if text is None:
        return frozenset()
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() != "agent_env_doctor_seen":
            continue
        seen.update(name.strip() for name in value.split(",") if name.strip())
    return frozenset(seen)


def _remind_after_dates(root: Path) -> dict[str, str]:
    """{plugin: "YYYY-MM-DD", ...} from .agent-mode.local's
    agent_env_doctor_remind_after=<plugin>:<date>[,<plugin>:<date>...]."""
    text = _read_text_bounded(root / ".agent-mode.local")
    if text is None:
        return {}
    dates: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() != "agent_env_doctor_remind_after":
            continue
        for entry in value.split(","):
            entry = entry.strip()
            if not entry or ":" not in entry:
                continue
            name, _, date_str = entry.partition(":")
            name = name.strip()
            date_str = date_str.strip()
            if name and date_str:
                dates[name] = date_str
    return dates


def _superpowers_pointer_seen(root: Path) -> bool:
    """True when .agent-mode.local's agent_env_doctor_superpowers_pointer_seen
    is exactly "true" — the coexistence pointer has already been shown once
    and must not repeat."""
    text = _read_text_bounded(root / ".agent-mode.local")
    if text is None:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "agent_env_doctor_superpowers_pointer_seen" and value.strip() == "true":
            return True
    return False


def _rewrite_agent_mode_keys(root: Path, updates: dict[str, str | None]) -> None:
    """Atomically rewrite .agent-mode.local, replacing each key in `updates`
    with its mapped full line text (or dropping the key's line entirely when
    the mapped value is None), and passing every other line through
    unmodified. A single shared writer for every "seen"-style flag this
    doctor records, so recording several flags from one evaluate() call is
    one read-modify-write instead of several stacked ones (each of which
    reopens the same race window against a concurrent SessionStart hook in
    another process/session).

    CRLF-preserving: reads via _read_agent_mode_text (matching
    check_agent_mode's own semantics), so an unrelated "dangerous\\r\\n" line
    (inert to the launcher's exact bash `case` match, which never sees a
    match against "dangerous\\r") is never silently normalized into an
    active "dangerous" line by this rewrite. Never raises: a write failure
    here must not block session start, matching every other check's
    contract."""
    if not updates:
        return
    config = root / ".agent-mode.local"
    try:
        text = _read_agent_mode_text(config) or ""
        lines = text.split("\n") if text else []
        if text.endswith("\n") and lines and lines[-1] == "":
            lines = lines[:-1]
        new_lines: list[str] = []
        written: set[str] = set()
        for line in lines:
            stripped = line.strip()
            key = stripped.partition("=")[0].strip() if "=" in stripped else None
            if key in updates:
                replacement = updates[key]
                if replacement is not None and key not in written:
                    new_lines.append(replacement)
                    written.add(key)
                continue
            new_lines.append(line)
        for key, replacement in updates.items():
            if replacement is not None and key not in written:
                new_lines.append(replacement)

        new_text = "\n".join(new_lines)
        if new_text and not new_text.endswith("\n"):
            new_text += "\n"
        tmp = config.with_name(config.name + ".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(config)
    except OSError:
        pass


def _superpowers_pointer_updates(shown: bool) -> dict[str, str | None]:
    """After showing the coexistence pointer once, record that so later
    sessions stay silent."""
    if not shown:
        return {}
    return {"agent_env_doctor_superpowers_pointer_seen": "agent_env_doctor_superpowers_pointer_seen=true"}


def _dormant_plugin_decision_updates(root: Path, decisions: list[dict]) -> dict[str, str | None]:
    """After showing the full nudge for a plugin (first sighting, or a
    remind_after date that has now passed), add it to agent_env_doctor_seen
    and drop it from agent_env_doctor_remind_after, so later sessions
    collapse to the short form instead of re-showing the full nudge every
    time."""
    newly_full = [d["plugin"] for d in decisions if d["display"] == "full"]
    if not newly_full:
        return {}

    seen = set(_seen_plugins(root)) | set(newly_full)
    remind_after = _remind_after_dates(root)
    for plugin in newly_full:
        remind_after.pop(plugin, None)

    return {
        "agent_env_doctor_seen": (
            f"agent_env_doctor_seen={','.join(sorted(seen))}" if seen else None
        ),
        "agent_env_doctor_remind_after": (
            "agent_env_doctor_remind_after="
            + ",".join(f"{p}:{d}" for p, d in sorted(remind_after.items()))
            if remind_after
            else None
        ),
    }


def collect_warnings(
    root: Path,
    env: dict,
    plugins_file: Path,
    home: Path,
    tmp_root: Path,
    now: float | None = None,
    today: date | None = None,
    dormant_plugin_warnings: list[str] | None = None,
    superpowers_warnings: list[str] | None = None,
) -> list[str]:
    """dormant_plugin_warnings and superpowers_warnings let a caller
    (evaluate()) pass in warnings derived from state it already computed
    once, instead of this function re-deriving them from disk a second time
    (bento-rdtn.2 review) -- computed fresh here only when omitted, e.g. by
    a caller that only wants collect_warnings' aggregate result."""
    warnings: list[str] = []
    warnings.extend(check_imports(root))
    warnings.extend(check_hook_binaries(root, env))
    warnings.extend(
        dormant_plugin_warnings
        if dormant_plugin_warnings is not None
        else check_dormant_plugins(
            root,
            installed_plugins(plugins_file),
            _skipped_plugins(root),
            _seen_plugins(root),
            _remind_after_dates(root),
            today,
        )
    )
    warnings.extend(
        superpowers_warnings
        if superpowers_warnings is not None
        else check_superpowers_coexistence(
            installed_plugins(plugins_file), _superpowers_pointer_seen(root)
        )
    )
    warnings.extend(check_agent_mode(root))
    warnings.extend(check_bare_primary(root))
    worktree_entries = _worktree_list_entries(root)
    warnings.extend(check_prunable_worktrees(root, entries=worktree_entries))
    warnings.extend(check_stale_previews(root, tmp_root, now=now))
    warnings.extend(check_worktree_root_orphans(root, home, entries=worktree_entries))
    warnings.extend(check_orphan_dolt_server(root))
    return warnings


def _plugins_file(home: Path, env: dict) -> Path:
    return home / ".claude" / "plugins" / "installed_plugins.json"


def evaluate(
    hook_input: dict,
    home: Path | None = None,
    env: dict | None = None,
    plugins_file: Path | None = None,
    tmp_root: Path | None = None,
    now: float | None = None,
    today: date | None = None,
) -> dict | None:
    """Return a SessionStart additionalContext payload, or None to stay silent."""
    environ = os.environ if env is None else env
    resolved_home = home or Path(environ.get("HOME", str(Path.home())))
    resolved_tmp_root = tmp_root if tmp_root is not None else Path("/tmp")
    resolved_today = today if today is not None else date.today()

    cwd = hook_input.get("cwd") or ""
    if not cwd or not os.path.isdir(cwd):
        return None
    root = Path(repo_root(cwd) or cwd)

    if _suppressed(root):
        return None

    pfile = plugins_file if plugins_file is not None else _plugins_file(resolved_home, environ)
    installed = installed_plugins(pfile)

    # Computed once and reused for both the warnings this session sees and
    # the decisions recorded to .agent-mode.local, so the two can never
    # silently desync (bento-rdtn.2 review).
    dormant_decisions = _dormant_plugin_decisions(
        root,
        installed,
        _skipped_plugins(root),
        _seen_plugins(root),
        _remind_after_dates(root),
        resolved_today,
    )
    dormant_plugin_warnings = [_format_dormant_plugin_warning(d) for d in dormant_decisions]

    superpowers_pointer_already_seen = _superpowers_pointer_seen(root)
    superpowers_warnings = check_superpowers_coexistence(installed, superpowers_pointer_already_seen)

    warnings = collect_warnings(
        root, environ, pfile, resolved_home, resolved_tmp_root, now=now, today=resolved_today,
        dormant_plugin_warnings=dormant_plugin_warnings,
        superpowers_warnings=superpowers_warnings,
    )

    # Record dormant-plugin decisions (first sighting or remind-after
    # expiry) and the superpowers pointer (first sighting) in one combined
    # rewrite, regardless of whether any *other* check also warned this
    # session -- one read-modify-write instead of two stacked ones, halving
    # the race window against a concurrent SessionStart hook in another
    # process/session touching the same .agent-mode.local.
    agent_mode_updates = _dormant_plugin_decision_updates(root, dormant_decisions)
    agent_mode_updates.update(_superpowers_pointer_updates(bool(superpowers_warnings)))
    _rewrite_agent_mode_keys(root, agent_mode_updates)

    if not warnings:
        return None

    body = "\n".join(f"  - {w}" for w in warnings)
    context = (
        "agent-env doctor found agent wiring that is silently broken (advisory, "
        "non-blocking):\n"
        f"{body}\n"
        "Each item is a guardrail or instruction that currently does nothing. Fix "
        "the wiring, or silence a specific inapplicable plugin's dormancy nudge "
        "with 'agent_env_doctor_skip_plugin=<name>' (comma-separated for "
        "multiple) in .agent-mode.local — every other check still runs. Only "
        "use 'agent_env_doctor=false' to disable this doctor entirely."
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
