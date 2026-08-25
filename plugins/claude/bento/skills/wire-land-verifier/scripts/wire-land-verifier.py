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
* `draft` requires explicit `--check` values and screens out obvious no-op
  commands and commands whose executable does not resolve.
* `validate` actually runs the staged wrapper and records a receipt.
* `apply` refuses unless the staged files still hash to the receipt's
  fingerprint and that receipt reported at least one selected check.

No-op screening is best-effort and cannot be complete: any command can do
nothing (`git status`, `ls`, a script whose body is commented out), and no
static check can prove a command is this repo's real gate. The binding
guarantee is the user explicitly confirming that the wired command is the
repo's actual landing gate; this CLI's checks only remove the obvious ways to
wire a gate that proves nothing by accident.

Subcommands: discover, draft, validate, apply.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

MANIFEST_REL = Path(".agent-plugins/bento/bento/land-work/verifier.json")
DEFAULT_WRAPPER_REL = "scripts/land-work-verifier.py"
STAGING_REL = Path("bento/wire-land-verifier")

# Commands that would make the verifier rubber-stamp a landing. A wrapper built
# from any of these reports "passed" while checking nothing. This list is a
# screen for obvious mistakes, NOT a proof of non-triviality -- see the module
# docstring and NO_OP_CAVEAT.
NO_OP_EXECUTABLES = frozenset(
    {"true", ":", "echo", "printf", "exit", "test", "[", "sleep"}
)

# Commands that merely set up an environment, a limit, or a runtime and then
# run their remaining argument as the real command, so a no-op hidden behind
# one is still a no-op. Each entry describes how to walk past that command's
# own options so screening lands on the real executable.
#
#   value_flags   flags that consume the following token as their value
#   positionals   positional arguments that precede the command (`timeout 5 CMD`)
#   assignments   NAME=VALUE tokens are part of the prefix (`env FOO=1 CMD`)
#   subcommands   a literal word must follow for this to be a prefix at all
#                 (`uv run CMD` is a prefix; `uv lock` is not)
#   script_flags  flags whose value is the command, as one shell string
#                 (`flock -c 'make test'`, `nix-shell --run 'make test'`)
class PrefixSpec(NamedTuple):
    value_flags: frozenset[str] = frozenset()
    positionals: int = 0
    assignments: bool = False
    subcommands: frozenset[str] = frozenset()
    script_flags: frozenset[str] = frozenset()


PREFIX_COMMANDS: dict[str, PrefixSpec] = {
    # environment / scheduling wrappers
    "env": PrefixSpec(
        value_flags=frozenset(
            {"-u", "--unset", "-S", "--split-string", "-C", "--chdir"}
        ),
        assignments=True,
    ),
    "nohup": PrefixSpec(),
    "setsid": PrefixSpec(),
    "nice": PrefixSpec(value_flags=frozenset({"-n", "--adjustment"})),
    "ionice": PrefixSpec(
        value_flags=frozenset(
            {"-c", "--class", "-n", "--classdata", "-p", "--pid"}
        )
    ),
    "stdbuf": PrefixSpec(
        value_flags=frozenset({"-i", "--input", "-o", "--output", "-e", "--error"})
    ),
    "time": PrefixSpec(value_flags=frozenset({"-f", "--format", "-o", "--output"})),
    "command": PrefixSpec(),
    "eatmydata": PrefixSpec(),
    "unbuffer": PrefixSpec(),
    "chronic": PrefixSpec(),
    # limits and retries
    "timeout": PrefixSpec(
        value_flags=frozenset({"-s", "--signal", "-k", "--kill-after"}),
        positionals=1,
    ),
    "retry": PrefixSpec(
        value_flags=frozenset({"-t", "--times", "-s", "--sleep", "-d", "--delay"})
    ),
    "flock": PrefixSpec(
        value_flags=frozenset(
            {"-w", "--wait", "--timeout", "-E", "--conflict-exit-code"}
        ),
        positionals=1,
        script_flags=frozenset({"-c", "--command"}),
    ),
    "nix-shell": PrefixSpec(script_flags=frozenset({"--run", "--command"})),
    # privilege wrappers
    "sudo": PrefixSpec(
        value_flags=frozenset(
            {
                "-u", "--user", "-g", "--group", "-p", "--prompt", "-C",
                "--close-from", "-h", "--host", "-r", "--role", "-t", "--type",
                "-T", "--command-timeout", "-U", "--other-user", "-D", "--chdir",
                "-R", "--chroot",
            }
        )
    ),
    "doas": PrefixSpec(value_flags=frozenset({"-u", "-C"})),
    "runuser": PrefixSpec(
        value_flags=frozenset({"-u", "--user", "-g", "--group", "-G", "--supp-group"})
    ),
    # argument plumbing
    "xargs": PrefixSpec(
        value_flags=frozenset(
            {
                "-a", "--arg-file", "-d", "--delimiter", "-E", "-I", "--replace",
                "-i", "-L", "--max-lines", "-l", "-n", "--max-args", "-P",
                "--max-procs", "-s", "--max-chars",
            }
        )
    ),
    # language/runtime task runners: only a prefix in their `run`/`exec` form
    "poetry": PrefixSpec(subcommands=frozenset({"run"})),
    "pipenv": PrefixSpec(subcommands=frozenset({"run"})),
    "uv": PrefixSpec(subcommands=frozenset({"run"})),
    "pdm": PrefixSpec(subcommands=frozenset({"run"})),
    "rye": PrefixSpec(subcommands=frozenset({"run"})),
    "hatch": PrefixSpec(subcommands=frozenset({"run"})),
    "bundle": PrefixSpec(subcommands=frozenset({"exec"})),
    "npm": PrefixSpec(subcommands=frozenset({"exec"})),
    "pnpm": PrefixSpec(subcommands=frozenset({"exec", "dlx"})),
    "yarn": PrefixSpec(subcommands=frozenset({"exec", "dlx"})),
    "npx": PrefixSpec(value_flags=frozenset({"-p", "--package"})),
    "conda": PrefixSpec(
        value_flags=frozenset({"-n", "--name", "-p", "--prefix"}),
        subcommands=frozenset({"run"}),
    ),
    "mamba": PrefixSpec(
        value_flags=frozenset({"-n", "--name", "-p", "--prefix"}),
        subcommands=frozenset({"run"}),
    ),
    "micromamba": PrefixSpec(
        value_flags=frozenset({"-n", "--name", "-p", "--prefix"}),
        subcommands=frozenset({"run"}),
    ),
    "pixi": PrefixSpec(
        value_flags=frozenset({"-e", "--environment", "--manifest-path"}),
        subcommands=frozenset({"run", "exec"}),
    ),
    "mise": PrefixSpec(subcommands=frozenset({"exec", "x"})),
    "direnv": PrefixSpec(subcommands=frozenset({"exec"}), positionals=1),
    # misc wrappers that take the command as their tail
    "watch": PrefixSpec(value_flags=frozenset({"-n", "--interval"})),
    "setarch": PrefixSpec(positionals=1),
}

# Prefixes that resolve their tail command inside a managed environment (a
# venv, a lockfile-pinned toolchain) rather than on the host PATH. Requiring
# their inner command to *also* resolve on the host PATH defeats the point of
# using the launcher: `uv run pytest` is a perfectly real gate even when the
# host has no `pytest` at all. Derived from PREFIX_COMMANDS so it can never
# drift from the table that defines what "run/exec form" means.
MANAGED_RUNTIME_LAUNCHERS = frozenset(
    name for name, spec in PREFIX_COMMANDS.items() if spec.subcommands
)

# Shell operators that `shlex.split` tokenizes like ordinary words. Without a
# shell to interpret them, `./test.sh && ./lint.sh` runs only `./test.sh`,
# with `&&` and `./lint.sh` passed through as inert, literal arguments -- a
# silently narrower check than the command looks like it performs.
_SHELL_ONLY_TOKENS = frozenset(
    {"&&", "||", ";", ";;", "|", "|&", "&", ">", ">>", "<", "<<"}
)

# Screening applied to *speculative* resolutions -- the branch taken when a
# prefix is handed a flag the table does not know, which may or may not consume
# the next token. Narrower than NO_OP_EXECUTABLES on purpose: `test` and `echo`
# plausibly appear as an ordinary argument (`nice -5 make test`), while these
# never mean real work.
SPECULATIVE_NO_OPS = frozenset({"true", ":", "sleep", "exit"})

SHELL_EXECUTABLES = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})

# Shell options that consume the following token, so the `-c` after them is not
# the first flag the walk sees.
SHELL_VALUE_FLAGS = frozenset(
    {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
)

INTERPRETERS = frozenset(
    {"python", "python2", "python3", "perl", "ruby", "node", "nodejs"}
)

# Inline interpreter bodies that evaluate to "do nothing".
# Shell punctuation that runs nothing on its own.
_SHELL_SEPARATORS = " \t\n\r;&|"
_SHELL_SEPARATOR_TOKENS = frozenset({";", ";;", "&", "&&", "|", "||"})

_NEGATIVE_NUMBER_RE = re.compile(r"^-\d+$")

# `shlex.split` only splits on whitespace, not shell metacharacters -- a
# separator glued to a word with no surrounding space (`echo prep; make
# test`) survives as one token ("prep;"). This peels a leading/trailing
# separator run off a token so `_split_shell_statements` still sees it as its
# own token, matching how a real shell lexer (not just shlex) would tokenize.
_SEP_ATTACHED_RE = re.compile(r"(;;|&&|\|\||;|&|\|)")

_TRIVIAL_SCRIPT_RE = re.compile(r"^[\s;]*(?:pass|None|0|true|1)?[\s;]*$")

NO_OP_CAVEAT = (
    "No-op screening is best-effort: it rejects commands that obviously do "
    "nothing, but it cannot prove that any accepted command is this repo's "
    "real landing gate. That guarantee comes only from the user confirming "
    "the gate command -- confirm it before `apply`."
)

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


def _unquote(value: str) -> str:
    """Strip one *matched* pair of surrounding quotes.

    A blanket ``strip("\"'")`` mangles ordinary lines like
    ``npm test -- --grep "smoke"`` into unbalanced text that shlex cannot parse.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].strip()
    return value


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
            command = _unquote(match.group(1).strip())
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
        try:
            words = shlex.split(command)
        except ValueError:
            # Unbalanced quoting in a `run:` line is that workflow's business,
            # not a reason to abort discovery. Skip the candidate.
            continue
        if not words:
            continue
        candidates.append(
            {"command": command, "source": source, "rank": _rank(words[0])}
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
    if separator and ("/" in name or name.strip().startswith(("./", "../"))):
        # A path before the first "::" means this was never a NAME::COMMAND
        # split at all -- it's a bare command whose own syntax uses "::", like
        # a pytest node id (`tests/test_x.py::test_case`). Treat the whole
        # string as the bare command instead of misparsing a path fragment as
        # the name and a test id as the command.
        separator = ""
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
    shell_token = next((t for t in argv if t in _SHELL_ONLY_TOKENS), None)
    if shell_token is not None:
        raise WireError(
            f"--check {raw!r} needs a shell to run as written: {shell_token!r} "
            "would be passed as a literal, inert argument instead of being "
            f"interpreted. Wrap it explicitly, e.g. {name}::bash -c "
            f"{shlex.quote(command)}, so the shell semantics actually run."
        )
    return {"name": name, "command": command, "argv": argv}


def _is_value(token: str) -> bool:
    """Whether a flag may claim this token as its value.

    A flag never consumes another flag (`bash -o -c true` does not hide the
    `-c`), but a negative number is a value (`nice -n -5 make test`).
    """
    return not token.startswith("-") or _NEGATIVE_NUMBER_RE.match(token) is not None


def _consume_options(spec: PrefixSpec, rest: list[str]) -> list[list[str]]:
    """Token lists left after one prefix's own options are removed.

    Returns more than one list when the prefix is handed a flag the table does
    not describe: such a flag may or may not consume the token after it, and
    guessing wrong is how `env -u NAME true` used to slip through. Both readings
    are returned; the first is the primary (flag takes no value), the rest are
    speculative and screened against SPECULATIVE_NO_OPS only.
    """
    speculative: list[list[str]] = []
    while rest:
        token = rest[0]
        if token == "--":
            rest = rest[1:]
            break
        if spec.assignments and "=" in token and not token.startswith("-"):
            rest = rest[1:]
            continue
        if not token.startswith("-") or token == "-":
            break
        if token in spec.value_flags and len(rest) > 1 and _is_value(rest[1]):
            rest = rest[2:]
            continue
        if "=" in token:  # --flag=value carries its own value
            rest = rest[1:]
            continue
        if not token.startswith("--") and token[:2] in spec.value_flags:
            rest = rest[1:]  # -n5, attached value
            continue
        if len(rest) > 2:
            speculative.append(rest[2:])
        rest = rest[1:]
    return [rest, *speculative]


def _script_flag_value(spec: PrefixSpec, rest: list[str]) -> str | None:
    """The shell-string command handed to a prefix's script flag, if any."""
    for index, token in enumerate(rest):
        flag, separator, attached = token.partition("=")
        if flag not in spec.script_flags:
            continue
        if separator:
            return attached
        return rest[index + 1] if index + 1 < len(rest) else ""
    return None


def _strip_one_prefix(argv: list[str]) -> list[list[str]] | None:
    """Peel one prefix command off ``argv``, or None if it is not one.

    Walks options, then any required subcommand word, then the prefix's own
    positional arguments, then options again -- the second option pass is what
    catches `timeout 5 -- true`, where the `--` only becomes visible once the
    duration has been consumed.
    """
    spec = PREFIX_COMMANDS.get(Path(argv[0]).name)
    if spec is None:
        return None
    inline = _script_flag_value(spec, argv[1:])
    if inline is not None:
        # The command is a shell string, not the tail of the argv. Screen the
        # string itself so `flock -c 'make test'` resolves to `make test`
        # instead of to a nonexistent executable named "make test".
        try:
            return [shlex.split(inline)]
        except ValueError:
            return [[]]
    results: list[list[str]] = []
    for branch in _consume_options(spec, argv[1:]):
        rest = branch
        if spec.subcommands:
            if not rest or rest[0] not in spec.subcommands:
                # `uv lock`, `yarn test`: the head is the real command.
                return None
            rest = _consume_options(spec, rest[1:])[0]
        for _ in range(spec.positionals):
            # Never consume the last token: it is the command, not the
            # prefix's own argument (`flock -c 'make test'`).
            if len(rest) > 1 and not rest[0].startswith("-"):
                rest = rest[1:]
            else:
                break
        results.append(_consume_options(spec, rest)[0])
    return results


def prefix_resolutions(argv: list[str]) -> list[list[str]]:
    """Every plausible real command behind a chain of prefix commands.

    ``resolutions[0]`` is the primary reading -- the one the table fully
    describes. Any others are speculative readings of an unknown flag.
    """
    # No iteration cap: every layer returns a strict suffix of its input, so a
    # chain of prefixes terminates on its own. A fixed budget just meant
    # `env env env ... true` walked out the far side unscreened.
    primary: list[str] = list(argv)
    speculative: list[list[str]] = []
    while primary:
        stripped = _strip_one_prefix(primary)
        if stripped is None:
            break
        primary, *rest = stripped
        speculative.extend(rest)
    resolved = [primary]
    for candidate in speculative[:8]:
        while candidate:
            stripped = _strip_one_prefix(candidate)
            if stripped is None:
                break
            candidate = stripped[0]
        resolved.append(candidate)
    return resolved


def strip_prefix_commands(argv: list[str]) -> list[str]:
    """The primary real command behind `env FOO=1 timeout 5 <command>`."""
    return prefix_resolutions(argv)[0]


def _primary_chain_executables(argv: list[str]) -> list[str]:
    """Executable basenames peeled off argv's primary reading, in order.

    The last entry is the final resolved command; everything before it is a
    prefix that ran it. Used to tell whether a managed-runtime launcher (`uv
    run`, `hatch run`, ...) sits anywhere ahead of the final command, since
    that changes how -- or whether -- its executable should be resolved.
    """
    names: list[str] = []
    current = list(argv)
    while current:
        names.append(Path(current[0]).name)
        stripped = _strip_one_prefix(current)
        if stripped is None:
            break
        current = stripped[0]
    return names


def _shell_walk(argv: list[str]) -> tuple[str | None, list[str]]:
    """Split a shell argv into (inline `-c` script, remaining operands).

    Walks the shell's own options rather than stopping at the first token that
    is not a bare `-x` flag, so `bash -o pipefail -c true` and
    `bash --rcfile FILE -c true` still expose their inline script. Clustered
    flags (`bash -lc`) and `sh -c -- SCRIPT` are handled; a long option is never
    mistaken for a cluster containing `c` (`--rcfile`).
    """
    rest = argv[1:]
    while rest:
        token = rest[0]
        if token == "--":
            return None, rest[1:]
        if token in {"-", "+"} or not token.startswith(("-", "+")):
            return None, rest  # a script FILE operand, not an inline script
        if token in SHELL_VALUE_FLAGS and len(rest) > 1 and _is_value(rest[1]):
            rest = rest[2:]
            continue
        if token.startswith(("--", "++")):
            rest = rest[1:]
            continue
        letters = token[1:]
        if "c" in letters:
            tail = rest[1:]
            while tail and tail[0] == "--":
                tail = tail[1:]
            return (tail[0] if tail else ""), tail[1:]
        if (
            letters
            and f"{token[0]}{letters[-1]}" in SHELL_VALUE_FLAGS
            and len(rest) > 1
            and _is_value(rest[1])
        ):
            rest = rest[2:]  # `sh -eo pipefail`
            continue
        rest = rest[1:]
    return None, []


def shell_inline_script(argv: list[str]) -> str | None:
    """Return the inline script of a `sh -c SCRIPT` argv, else None."""
    return _shell_walk(argv)[0]


def interpreter_inline_script(argv: list[str]) -> str | None:
    """Return the inline program of `python -c ...` / `node -e ...`, else None."""
    rest = argv[1:]
    for index, token in enumerate(rest):
        if token in {"-c", "-e", "--eval"} or (
            token.startswith("-")
            and not token.startswith("--")
            and ("c" in token[1:] or "e" in token[1:])
        ):
            return rest[index + 1] if index + 1 < len(rest) else ""
    return None


def no_op_reason(argv: list[str], depth: int = 0) -> str | None:
    """Why this argv obviously does nothing, or None if it might be real."""
    resolutions = prefix_resolutions(argv)
    reason = _resolved_no_op_reason(resolutions[0], depth)
    if reason is not None:
        return reason
    for candidate in resolutions[1:]:
        if candidate and Path(candidate[0]).name in SPECULATIVE_NO_OPS:
            name = Path(candidate[0]).name
            return (
                f"read one way its options run {name!r}, which does no work"
            )
    return None


def _split_shell_statements(tokens: list[str]) -> list[list[str]]:
    """Break a flat, already-`shlex.split` token list at shell separators.

    `shlex.split` doesn't know `;`/`&&`/`|` are special -- they come out as
    ordinary tokens. Splitting on them here (rather than discarding them and
    judging the flattened remainder as one command) is what lets a compound
    script be screened statement by statement instead of by its first word.
    """
    expanded: list[str] = []
    for token in tokens:
        pieces = [piece for piece in _SEP_ATTACHED_RE.split(token) if piece]
        expanded.extend(pieces or [token])

    statements: list[list[str]] = []
    current: list[str] = []
    for token in expanded:
        if token in _SHELL_SEPARATOR_TOKENS:
            if current:
                statements.append(current)
            current = []
        else:
            current.append(token)
    if current:
        statements.append(current)
    return statements


def _resolved_no_op_reason(argv: list[str], depth: int) -> str | None:
    if not argv:
        return "it runs no command at all"
    head = Path(argv[0]).name
    if head in NO_OP_EXECUTABLES:
        return f"{head!r} does no work"
    if depth < 4 and head in SHELL_EXECUTABLES:
        script, operands = _shell_walk(argv)
        if script is None and not operands:
            # `bash`, `bash -s`: no script argument at all, so the gate is
            # whatever happens to be on stdin -- nothing, under land-work.
            return f"{head!r} is given no script to run"
        if script is not None:
            if not script.strip(_SHELL_SEPARATORS):
                return "its inline shell script is empty"
            try:
                tokens = shlex.split(script)
            except ValueError:
                tokens = []
            # Split on statement separators rather than stripping them and
            # judging the flattened result as one command: `echo prep; make
            # test` would otherwise be judged as starting with `echo` alone
            # and rejected, even though `make test` -- the actual gate -- is
            # right there. The whole script is a no-op only if EVERY
            # statement is; one real statement makes the compound real.
            statements = _split_shell_statements(tokens)
            statement_reasons = [
                no_op_reason(statement, depth + 1) for statement in statements
            ]
            if statements and all(reason is not None for reason in statement_reasons):
                return (
                    "it wraps a shell command that does nothing "
                    f"({statement_reasons[0]})"
                )
    if head in INTERPRETERS:
        program = interpreter_inline_script(argv)
        if program is not None and _TRIVIAL_SCRIPT_RE.match(program):
            return f"{head!r} is handed an inline program that does nothing"
    return None


def reject_no_ops(check: dict) -> None:
    reason = no_op_reason(check["argv"])
    if reason is None:
        return
    raise WireError(
        f"--check {check['command']!r} looks like a no-op: {reason}. A verifier "
        "built from it would report 'passed' without running a real check. "
        + NO_OP_CAVEAT
    )


def resolve_executable(check: dict, worktree: Path) -> None:
    # Resolve past `env FOO=1` / `timeout 5` first: the executable that has to
    # exist is the real command, not the prefix that runs it.
    resolved = strip_prefix_commands(check["argv"])
    argv0 = resolved[0] if resolved and not resolved[0].startswith("-") else check["argv"][0]
    if "/" in argv0:
        candidate = (worktree / argv0).resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return
        raise WireError(
            f"--check {check['command']!r} points at {argv0!r}, which is not an "
            f"executable file in {worktree}"
        )
    if shutil.which(argv0) is None:
        chain = _primary_chain_executables(check["argv"])
        # A managed-runtime launcher (`uv run`, `hatch run`, ...) resolves its
        # tail command inside its own environment, not the host PATH -- ahead
        # of it in the chain means behind it, not the leading one, since the
        # chain ends with the final command itself.
        if any(name in MANAGED_RUNTIME_LAUNCHERS for name in chain[:-1]):
            return
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


def render_manifest(wrapper_rel: Path, verified_noop: list | None = None) -> str:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "command": [f"./{wrapper_rel.as_posix()}"],
                "verified_noop": verified_noop or [],
            },
            indent=2,
        )
        + "\n"
    )


_GLOB_CHARS = frozenset("*?[]")


def _verified_noop_problems(entries: list) -> list[str]:
    """Structural problems in a `verified_noop` list, per the contract in
    `catalog/skills/land-work/references/project-verifier.md`.

    Mirrors the shape `land-work-run-verifier.py` and
    `lifecycle_extensions._validate_verifier_shape` enforce at real landing
    time. Carrying forward (or emitting) a shape they reject is false
    confidence at setup time, not a working exemption.
    """
    problems: list[str] = []
    seen_normalized: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(
                f"verified_noop[{index}] must be an object with 'path' and "
                f"'reason', not {entry!r}"
            )
            continue
        path_value = entry.get("path")
        reason_value = entry.get("reason")
        if not isinstance(path_value, str) or not path_value:
            problems.append(f"verified_noop[{index}].path must be a nonempty string")
        elif path_value.startswith("/"):
            problems.append(f"verified_noop[{index}].path must not be absolute: {path_value!r}")
        elif any(char in _GLOB_CHARS for char in path_value):
            problems.append(f"verified_noop[{index}].path must not be a glob: {path_value!r}")
        elif path_value.endswith("/"):
            problems.append(
                f"verified_noop[{index}].path must not be a directory/prefix "
                f"entry: {path_value!r}"
            )
        else:
            # Mirror land-work-run-verifier.py's own normalization exactly: a
            # path that is only "." segments and separators (".", "./", "./.")
            # normalizes to nothing, which the real validator rejects as an
            # empty path even though the raw string is nonempty here.
            segments = [s for s in path_value.split("/") if s]
            if any(s == ".." for s in segments):
                problems.append(
                    f"verified_noop[{index}].path must not contain '..': {path_value!r}"
                )
            else:
                normalized = "/".join(s for s in segments if s != ".")
                if not normalized:
                    problems.append(
                        f"verified_noop[{index}].path normalizes to an empty path: "
                        f"{path_value!r}"
                    )
                elif normalized in seen_normalized:
                    problems.append(
                        f"verified_noop[{index}].path duplicates another entry once "
                        f"normalized: {path_value!r}"
                    )
                else:
                    seen_normalized.add(normalized)
        if not isinstance(reason_value, str) or not reason_value:
            problems.append(f"verified_noop[{index}].reason must be a nonempty string")
    return problems


def existing_verified_noop(worktree: Path) -> list:
    """Exemptions already recorded in the repo's manifest, if any.

    Re-wiring must not silently drop them: land-work would then fail closed on
    paths the user had deliberately exempted, with no record of why. But
    carrying forward a shape land-work's own contract already rejects is worse
    than dropping it -- refuse instead so the problem is visible now rather
    than as a mysterious landing failure later.
    """
    path = worktree / MANIFEST_REL
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    existing = data.get("verified_noop")
    if not isinstance(existing, list):
        return []
    problems = _verified_noop_problems(existing)
    if problems:
        raise WireError(
            f"{MANIFEST_REL}'s existing verified_noop entries do not satisfy "
            "the verifier contract land-work enforces at landing time, so "
            "carrying them forward would be false confidence:\n  "
            + "\n  ".join(problems)
            + "\nFix or remove them in the existing manifest before re-running draft."
        )
    return existing


def require_repo_root(worktree: Path) -> Path:
    """Reject a worktree that is not the repo root.

    Everything downstream (`land-work-run-verifier.py`, the manifest lookup,
    the wrapper's own REPO_ROOT) is anchored at the repo root. Writing the
    manifest into a subdirectory reports success while leaving land-work with
    nothing to find.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=worktree,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WireError(f"{worktree} is not inside a git worktree")
    root = Path(result.stdout.strip()).resolve()
    if root != worktree.resolve():
        raise WireError(
            f"{worktree} is not the root of its git worktree ({root}). land-work "
            f"looks for {MANIFEST_REL} at the root only, so re-run with "
            f"--worktree {root}"
        )
    return root


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


def _reject_traversal(rel: Path) -> None:
    if rel.is_absolute():
        raise WireError(f"{rel} must be a relative path inside the worktree")
    if ".." in rel.parts:
        raise WireError(f"{rel} must not contain '..'")
    if ".git" in rel.parts:
        raise WireError(f"{rel} is inside .git, which wire-land-verifier refuses to touch")


def _contained_path(worktree: Path, rel: Path) -> Path:
    """Require every ancestor directory in `rel` to be real, not a symlink.

    A symlinked ancestor breaks two things at once, not just one: it can put
    the write outside the worktree entirely (the original concern), but even
    an ancestor symlinked to somewhere *else inside* the worktree is still
    wrong -- the generated wrapper's `REPO_ROOT = Path(__file__).resolve()
    .parents[N]` uses N from the *lexical* depth of the wrapper path, while
    `resolve()` follows the symlink to the real physical depth, so the two
    can silently disagree. It can also make two lexically different paths
    (e.g. the wrapper path and MANIFEST_REL) alias the same real file,
    defeating the lexical collision check in `draft`. Requiring every
    ancestor to be a real directory rules out both at once and is simpler
    than trying to compare resolved paths after the fact.

    Called again at each write point (not just at `draft` time), since an
    ancestor can be replaced with a symlink after drafting and before
    `validate`/`apply` actually touch the filesystem. The leaf itself is not
    checked here: it may still be a symlink (a dangling one included) --
    `_replace` unlinks it rather than writing through it, regardless of where
    it points, so leaf symlinks are handled downstream, not here.
    """
    _reject_traversal(rel)
    current = worktree
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise WireError(
                f"{rel} has a symlinked ancestor directory ({current}); "
                "wire-land-verifier refuses to write through it"
            )
    return worktree / rel


def draft(worktree: Path, raw_checks: list[str], wrapper_path: str) -> dict:
    wrapper_rel = Path(wrapper_path)
    _contained_path(worktree, wrapper_rel)
    if not wrapper_rel.name or wrapper_rel == Path("."):
        raise WireError(f"--wrapper-path {wrapper_path!r} must name a file, not a directory")
    if wrapper_rel == MANIFEST_REL:
        raise WireError(
            f"--wrapper-path must not be {MANIFEST_REL.as_posix()!r}: apply would "
            "overwrite the wrapper with the manifest right after installing it"
        )

    checks = [parse_check(raw) for raw in raw_checks]
    for check in checks:
        reject_no_ops(check)
        resolve_executable(check, worktree)

    carried = existing_verified_noop(worktree)
    wrapper_body = render_wrapper(checks, wrapper_rel)
    manifest_body = render_manifest(wrapper_rel, carried)

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
        "carried_verified_noop": carried,
        "caveat": NO_OP_CAVEAT,
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


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the whole process group `start_new_session=True` created, and reap it.

    Covers every exit from `communicate()`, not just a reported timeout: a
    KeyboardInterrupt or other interruption must still reach the group, or a
    gate that backgrounds work keeps running -- and can keep mutating the
    repo -- detached from this process after it's gone.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.communicate()  # reap; the group is dead so this cannot hang


@contextlib.contextmanager
def _reap_group_on_sigterm(proc: subprocess.Popen):
    """Kill the process group on SIGTERM too, not just our own exceptions.

    `start_new_session=True` detaches `proc` into its own process group, so
    an external SIGTERM aimed only at *this* process's PID -- not a
    foreground Ctrl-C, which the terminal sends to the whole group -- never
    reaches it on its own. A Python exception handler cannot catch that
    either: the default SIGTERM disposition terminates the process before any
    `except`/`finally` gets a chance to run. Installing a handler for the
    duration of the call is what actually closes the gap.
    """
    def _on_term(signum: int, _frame: object) -> None:
        _kill_process_group(proc)
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, _on_term)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def validate(worktree: Path, timeout: int) -> tuple[dict, int]:
    staging, state = _read_state(worktree)
    runner = staging / "wrapper"
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)

    # The fingerprint covers the manifest's bytes, but only the wrapper file is
    # actually executed below -- nothing else ties the manifest's `command` to
    # what just ran. A manifest hand-edited in staging before this point (even
    # though it still hashes correctly) could point `command` at some other,
    # never-executed script and still receive a receipt. Refuse before running
    # anything if the two have already drifted apart.
    manifest = json.loads((staging / "verifier.json").read_text(encoding="utf-8"))
    wrapper_rel_check = Path(state["wrapper_rel"])
    expected_command = [f"./{wrapper_rel_check.as_posix()}"]
    if manifest.get("command") != expected_command:
        raise WireError(
            f"the staged manifest's command {manifest.get('command')!r} does not "
            f"match the wrapper being validated ({expected_command!r}); the draft "
            "was edited inconsistently. Re-run `draft` before `validate`"
        )

    # Hash what is about to run, not what `draft` recorded: a wrapper edited by
    # hand in staging is still a wrapper this run genuinely proved, and `apply`
    # compares against the bytes on disk.
    executed_fingerprint = _staged_fingerprint(staging, state)

    # Run from a unique sibling of the real target rather than from the target
    # itself. The wrapper's REPO_ROOT is computed from its own path depth, so
    # any name in the same directory resolves identically -- and staging beside
    # the user's file instead of on top of it means `validate` never reads,
    # replaces, or has to restore anything the user wrote.
    wrapper_rel = Path(state["wrapper_rel"])
    _contained_path(worktree, wrapper_rel)
    scratch = worktree / wrapper_rel.parent / f".{wrapper_rel.stem}.{os.getpid()}.tmp.py"
    _sweep_stale_scratch(scratch.parent, wrapper_rel.stem)
    created_dirs = _missing_ancestors(scratch.parent)
    scratch.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runner, scratch)
    scratch.chmod(scratch.stat().st_mode | stat.S_IXUSR)
    try:
        # A plain `subprocess.run(..., timeout=...)` only kills `scratch`
        # itself; a gate that backgrounds work (`sleep 30 &`) keeps mutating
        # the repo after this CLI has already reported failure and exited.
        # `start_new_session=True` puts `scratch` and anything it spawns in
        # their own process group, so a timeout can reach all of it.
        proc = subprocess.Popen(
            [str(scratch)],
            cwd=worktree,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        with _reap_group_on_sigterm(proc):
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_process_group(proc)
                return {
                    "schema_valid": False,
                    "error": f"verifier did not finish within {timeout}s",
                }, 1
            except BaseException:
                # Not just TimeoutExpired: a KeyboardInterrupt or other
                # in-process interruption during communicate() must still
                # reach the group, or the gate (and whatever it backgrounds)
                # keeps running detached from this process after it's gone.
                _kill_process_group(proc)
                raise
        result = subprocess.CompletedProcess(
            [str(scratch)], proc.returncode, stdout, stderr
        )
    finally:
        _discard_scratch(scratch, created_dirs)

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
            for entry in checks:
                if not isinstance(entry, dict) or entry.get("status") not in {
                    "passed", "failed",
                }:
                    problems.append(
                        f"selected_checks entry {entry!r} has no valid 'status'"
                    )
            any_check_failed = any(
                isinstance(c, dict) and c.get("status") == "failed" for c in checks
            )
            if any_check_failed and parsed.get("status") == "passed":
                problems.append(
                    "a selected check reports status 'failed' but the top-level "
                    "status is 'passed' -- the wrapper is not honest about its own "
                    "result"
                )
        if result.returncode != 0 and parsed.get("status") == "passed":
            problems.append(
                f"the wrapper exited {result.returncode} but reported status "
                "'passed' -- the wrapper is not honest about its own result"
            )

    schema_valid = not problems
    selected_checks = (parsed or {}).get("selected_checks")
    payload = {
        "worktree": str(worktree),
        "schema_valid": schema_valid,
        "status": (parsed or {}).get("status"),
        "selected_check_count": len(selected_checks) if isinstance(selected_checks, list) else 0,
        "problems": problems,
        "exit_code": result.returncode,
        "draft_edited": executed_fingerprint != state.get("fingerprint"),
        "stderr_tail": result.stderr[-2000:],
    }

    if schema_valid:
        state["receipt"] = {
            "fingerprint": executed_fingerprint,
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


def _missing_ancestors(directory: Path) -> list[Path]:
    """Directories `mkdir(parents=True)` would create, deepest first."""
    missing: list[Path] = []
    current = directory
    while not current.exists() and current != current.parent:
        missing.append(current)
        current = current.parent
    return missing


def _sweep_stale_scratch(directory: Path, stem: str) -> None:
    """Drop scratch copies left by an earlier run that was killed mid-gate.

    A killed `validate` cannot clean up after itself; the next one can, as long
    as it leaves alone a copy some other live process is still running.
    """
    if not directory.is_dir():
        return
    for path in directory.glob(f".{stem}.*.tmp.py"):
        try:
            pid = int(path.name.split(".")[-3])
        except (IndexError, ValueError):
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def _discard_scratch(path: Path, created_dirs: list[Path]) -> None:
    """Remove the scratch copy `validate` ran, and any directory it created."""
    path.unlink(missing_ok=True)
    for directory in created_dirs:
        try:
            directory.rmdir()
        except OSError:
            break


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------


def _staged_fingerprint(staging: Path, state: dict) -> str:
    """Hash what is actually on disk, not what state.json remembers.

    Comparing the receipt against `state["fingerprint"]` is vacuous: validate
    copies one field to the other inside the same file. Only re-reading the
    staged bytes can detect a wrapper swapped out after validation.
    """
    wrapper = staging / "wrapper"
    manifest = staging / "verifier.json"
    if not wrapper.is_file() or not manifest.is_file():
        raise WireError("the staged draft is incomplete; re-run `draft`")
    return _fingerprint(
        wrapper.read_text(encoding="utf-8"),
        manifest.read_text(encoding="utf-8"),
        Path(state["wrapper_rel"]),
    )


def _replace(source: Path, target: Path) -> None:
    """Install `source` AT `target`, replacing a symlink rather than following it.

    Copies through a same-directory temp file and renames it into place with
    `os.replace` (atomic on the same filesystem) instead of copying directly
    onto `target`: a crash or error mid-copy can then never leave a truncated
    file there, only the old content or the new content.
    """
    if target.is_symlink():
        target.unlink()
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    shutil.copy2(source, tmp)
    os.replace(tmp, target)


def _snapshot(path: Path) -> tuple[str, str | bytes, int | None] | None:
    """What is at `path`, captured well enough to put back exactly.

    `is_file()` follows a symlink: naively snapshotting via `read_bytes()` on
    a symlinked path would capture the *target's* content and mode, and
    restoring that later would replace the symlink with a plain-file copy --
    silently changing the repo's structure instead of restoring it. A symlink
    (dangling or not) is captured by its link target instead.
    """
    if path.is_symlink():
        return "symlink", os.readlink(path), None
    if path.is_file():
        return "file", path.read_bytes(), path.stat().st_mode
    return None


def _restore(snapshot: tuple[str, str | bytes, int | None] | None, path: Path) -> None:
    """Put back what `_snapshot` captured -- prior content, symlink, or absence."""
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    kind, payload, mode = snapshot
    path.unlink(missing_ok=True)
    if kind == "symlink":
        path.symlink_to(payload)
        return
    tmp = path.with_name(f".{path.name}.{os.getpid()}.restore")
    tmp.write_bytes(payload)
    tmp.chmod(mode)
    os.replace(tmp, path)


def apply(worktree: Path, force: bool) -> dict:
    staging, state = _read_state(worktree)
    receipt = state.get("receipt")
    if not receipt:
        raise WireError(
            "no validation receipt; run `wire-land-verifier.py validate` before "
            "`apply` so the wrapper is never installed unproven"
        )
    staged_fingerprint = _staged_fingerprint(staging, state)
    if receipt.get("fingerprint") != staged_fingerprint:
        raise WireError(
            "the staged files no longer hash to the validated fingerprint; the "
            "draft changed (or was tampered with) after validation. Re-run "
            "`draft` and `validate` before `apply`"
        )
    if receipt.get("selected_check_count", 0) < 1:
        raise WireError(
            "the validated wrapper reported zero selected checks; refusing to "
            "install a verifier that cannot gate a landing"
        )

    # lexists, not exists: a symlink at either path is something the user put
    # there, and a dangling one must still stop us. exists() follows the link,
    # so it reports "nothing here" and copy2 would then write through the link
    # to an undeclared path.
    manifest_path = _contained_path(worktree, MANIFEST_REL)
    if os.path.lexists(manifest_path) and not force:
        raise WireError(
            f"{MANIFEST_REL} already exists; re-run with --force to replace it"
        )

    wrapper_path = _contained_path(worktree, Path(state["wrapper_rel"]))
    if os.path.lexists(wrapper_path) and not force:
        raise WireError(
            f"{state['wrapper_rel']} already exists; choose another --wrapper-path "
            "or re-run with --force"
        )

    # Best-effort two-file consistency: if the manifest write fails after the
    # wrapper is already replaced, put the wrapper back rather than leaving a
    # new wrapper live under an unchanged (and now stale-pointing) manifest.
    wrapper_backup = _snapshot(wrapper_path)
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    _replace(staging / "wrapper", wrapper_path)
    wrapper_path.chmod(wrapper_path.stat().st_mode | 0o111)

    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        _replace(staging / "verifier.json", manifest_path)
    except OSError:
        _restore(wrapper_backup, wrapper_path)
        raise

    return {
        "worktree": str(worktree),
        "applied": True,
        "wrapper": state["wrapper_rel"],
        "manifest": MANIFEST_REL.as_posix(),
        "validated_status": receipt.get("status"),
        "caveat": NO_OP_CAVEAT,
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
        require_repo_root(worktree)
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
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
