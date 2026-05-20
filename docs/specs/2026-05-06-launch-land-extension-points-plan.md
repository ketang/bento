# Launch-Work / Land-Work Extension Points Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `pre` and `post` extension points to `launch-work` and `land-work`, supporting both executable script hooks (existing mechanism, generalized) and plain-language prose actions (new), with init.d-style numeric-prefix ordering.

**Architecture:** A single Python helper (`run-lifecycle-extensions.py`) under `launch-work/scripts/` exposes a `discover` subcommand (list extensions in execution order) and a `run-hooks` subcommand (execute hooks at a position with the env-var protocol, TTY detection, optional opt-in timeout, and exit-code semantics). Two reference docs (`project-hooks.md`, rewritten; `project-actions.md`, new) define the contracts. Both SKILL.md files invoke the helper at `pre` and `post` and have prose steps that read action files in order.

**Tech Stack:** Python 3 stdlib (`subprocess`, `pathlib`, `os`, `argparse`, `json`); pytest/unittest in `tests/launch_work/` and `tests/land_work/`.

**Spec:** `docs/specs/2026-05-06-launch-land-extension-points-design.md`.

---

## File Structure

**Create:**
- `catalog/skills/launch-work/scripts/lifecycle_extensions.py` — shared Python module: discovery rules (XDG chain, numeric-prefix sort, exclusion rules) and hook-runner internals.
- `catalog/skills/launch-work/scripts/run-lifecycle-extensions.py` — CLI front end with `discover` and `run-hooks` subcommands.
- `catalog/skills/launch-work/references/project-actions.md` — contract for prose actions.
- `tests/launch_work/test_lifecycle_extensions_discover.py` — unit tests for discovery rules.
- `tests/launch_work/test_lifecycle_extensions_run_hooks.py` — unit tests for the hook runner (env vars, exit codes, TTY signal, timeout, advisory mode).

**Modify:**
- `catalog/skills/launch-work/references/project-hooks.md` — rewritten to describe the new layout, prefix convention, env protocol, TTY/timeout, exit codes, advisory rule.
- `catalog/skills/launch-work/SKILL.md` — workflow steps replace the single mid-skill hook invocation with `pre` and `post` extension calls; add a step to read prose actions in order.
- `catalog/skills/land-work/SKILL.md` — same: `pre` and `post` extension calls, advisory mode at `post`.

**Why one CLI, not two:** the same discovery + runner logic serves both skills. Land-work invokes the helper with `--skill land-work` and (for `post` only) `--advisory`.

**Why a separate `lifecycle_extensions.py` module from the CLI:** the CLI script is `run-lifecycle-extensions.py` (hyphen, by convention with other scripts here), but Python imports require underscores. Splitting the importable logic from the CLI shim keeps tests clean and lets the runner internals be unit-tested without subprocesses.

---

## Task 1: Discovery rules — pure logic with tests

**Files:**
- Create: `catalog/skills/launch-work/scripts/lifecycle_extensions.py`
- Test: `tests/launch_work/test_lifecycle_extensions_discover.py`

This task implements the file-discovery logic only — no subprocess execution, no env vars, no I/O beyond reading directories.

- [ ] **Step 1: Write the failing test for prefix-sorted discovery**

Create `tests/launch_work/test_lifecycle_extensions_discover.py`:

```python
import os
import stat
import tempfile
import unittest
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "catalog/skills/launch-work/scripts"))

import lifecycle_extensions  # type: ignore  # noqa: E402


def _write(path: Path, content: str = "x", executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class DiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_hooks_sorted_by_numeric_prefix(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "20-second.sh", executable=True)
        _write(d / "10-first.sh", executable=True)
        _write(d / "30-third.sh", executable=True)

        result = lifecycle_extensions.discover_directory(d, kind="hooks")

        self.assertEqual(
            [p.name for p in result.files],
            ["10-first.sh", "20-second.sh", "30-third.sh"],
        )
        self.assertEqual(result.warnings, [])
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_discover.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lifecycle_extensions'`.

- [ ] **Step 3: Create the module with the minimal discover_directory**

Create `catalog/skills/launch-work/scripts/lifecycle_extensions.py`:

```python
"""Discover and run launch-work / land-work project extensions.

This module is the importable core. The CLI front end is run-lifecycle-extensions.py
in the same directory.

Layout under `<root>/.agent-plugins/bento/bento/`:

    <skill>/<kind>/<position>/<two-digit>-<slug>.<ext>

where <skill> is launch-work or land-work, <kind> is hooks or actions,
<position> is pre or post. <ext> is shell-executable for hooks, .md for
actions.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PREFIX_RE = re.compile(r"^(\d{2})-(.+)$")
BACKUP_SUFFIXES = ("~", ".bak", ".swp", ".orig")


@dataclass
class DiscoveryResult:
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def discover_directory(directory: Path, kind: str) -> DiscoveryResult:
    """Return ordered, filtered files from one position directory.

    kind is "hooks" or "actions".
    """
    result = DiscoveryResult()
    if not directory.is_dir():
        return result

    candidates: list[tuple[int, str, Path]] = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        name = entry.name
        if name.startswith("."):
            continue
        if name.endswith(BACKUP_SUFFIXES):
            continue
        if "/" in name or "\\" in name:
            continue
        if not entry.is_file():
            continue

        match = PREFIX_RE.match(name)
        if match is None:
            result.warnings.append(
                f"{entry}: filename does not start with two-digit prefix; ignored"
            )
            continue

        if kind == "hooks":
            mode = entry.stat().st_mode
            is_executable = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
            if not is_executable:
                continue
        elif kind == "actions":
            if entry.suffix != ".md":
                continue
        else:
            raise ValueError(f"unknown kind: {kind!r}")

        candidates.append((int(match.group(1)), name, entry))

    candidates.sort(key=lambda t: (t[0], t[1]))
    result.files = [p for _, _, p in candidates]
    return result
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_discover.py -v`
Expected: PASS — `test_hooks_sorted_by_numeric_prefix`.

- [ ] **Step 5: Add tests for ties, backups, hidden files, missing prefix**

Append to the same test file:

```python
    def test_ties_break_lexicographically(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "30-bbb.sh", executable=True)
        _write(d / "30-aaa.sh", executable=True)

        result = lifecycle_extensions.discover_directory(d, kind="hooks")
        self.assertEqual([p.name for p in result.files], ["30-aaa.sh", "30-bbb.sh"])

    def test_hidden_and_backups_silently_ignored(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "10-real.sh", executable=True)
        _write(d / ".hidden.sh", executable=True)
        _write(d / "20-edited.sh~", executable=True)
        _write(d / "30-orig.sh.bak", executable=True)

        result = lifecycle_extensions.discover_directory(d, kind="hooks")
        self.assertEqual([p.name for p in result.files], ["10-real.sh"])
        self.assertEqual(result.warnings, [])

    def test_missing_prefix_warns_and_skips(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "10-good.sh", executable=True)
        _write(d / "no-prefix.sh", executable=True)

        result = lifecycle_extensions.discover_directory(d, kind="hooks")
        self.assertEqual([p.name for p in result.files], ["10-good.sh"])
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("no-prefix.sh", result.warnings[0])

    def test_hooks_skip_non_executable(self) -> None:
        d = self.root / "launch-work/hooks/pre"
        _write(d / "10-yes.sh", executable=True)
        _write(d / "20-no.sh", executable=False)

        result = lifecycle_extensions.discover_directory(d, kind="hooks")
        self.assertEqual([p.name for p in result.files], ["10-yes.sh"])

    def test_actions_skip_non_md(self) -> None:
        d = self.root / "launch-work/actions/pre"
        _write(d / "10-good.md")
        _write(d / "20-not-md.txt")

        result = lifecycle_extensions.discover_directory(d, kind="actions")
        self.assertEqual([p.name for p in result.files], ["10-good.md"])

    def test_missing_directory_returns_empty(self) -> None:
        result = lifecycle_extensions.discover_directory(self.root / "nope", kind="hooks")
        self.assertEqual(result.files, [])
        self.assertEqual(result.warnings, [])
```

- [ ] **Step 6: Run all tests and confirm they pass**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_discover.py -v`
Expected: PASS — all six tests green.

- [ ] **Step 7: Add the XDG-chain enumerator with a test**

Append to `lifecycle_extensions.py`:

```python
def _candidate_roots(repo_root: Path) -> list[Path]:
    """Return the ordered XDG chain of agent-plugins roots."""
    roots: list[Path] = []
    repo_root_dir = (repo_root / ".agent-plugins/bento/bento").resolve()
    roots.append(repo_root_dir)

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        roots.append(Path(xdg) / "agent-plugins/bento/bento")
    else:
        roots.append(Path.home() / ".config/agent-plugins/bento/bento")

    return roots


def discover(
    repo_root: Path,
    skill: str,
    kind: str,
    position: str,
) -> DiscoveryResult:
    """Discover extensions for (skill, kind, position) across the XDG chain.

    Files from earlier roots come first; within each root, files are
    sorted by the rules in discover_directory.
    """
    if skill not in ("launch-work", "land-work"):
        raise ValueError(f"unknown skill: {skill!r}")
    if kind not in ("hooks", "actions"):
        raise ValueError(f"unknown kind: {kind!r}")
    if position not in ("pre", "post"):
        raise ValueError(f"unknown position: {position!r}")

    combined = DiscoveryResult()
    for root in _candidate_roots(repo_root):
        sub = root / skill / kind / position
        result = discover_directory(sub, kind=kind)
        combined.files.extend(result.files)
        combined.warnings.extend(result.warnings)
    return combined
```

Append to the test file:

```python
    def test_xdg_chain_orders_repo_first_then_user(self) -> None:
        repo = self.root / "repo"
        user = self.root / "userhome"
        os.environ["XDG_CONFIG_HOME"] = str(user / ".config")
        try:
            _write(
                repo / ".agent-plugins/bento/bento/launch-work/hooks/pre/10-repo.sh",
                executable=True,
            )
            _write(
                user / ".config/agent-plugins/bento/bento/launch-work/hooks/pre/10-user.sh",
                executable=True,
            )
            result = lifecycle_extensions.discover(repo, "launch-work", "hooks", "pre")
            self.assertEqual(
                [p.name for p in result.files],
                ["10-repo.sh", "10-user.sh"],
            )
        finally:
            del os.environ["XDG_CONFIG_HOME"]
```

- [ ] **Step 8: Run all tests**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_discover.py -v`
Expected: PASS — seven tests.

- [ ] **Step 9: Commit**

```bash
git add catalog/skills/launch-work/scripts/lifecycle_extensions.py tests/launch_work/test_lifecycle_extensions_discover.py
git commit -m "feat(extensions): add discovery module with numeric-prefix ordering and XDG chain (bento-5v2)"
```

---

## Task 2: CLI front end — `discover` subcommand

**Files:**
- Create: `catalog/skills/launch-work/scripts/run-lifecycle-extensions.py`
- Test: `tests/launch_work/test_lifecycle_extensions_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/launch_work/test_lifecycle_extensions_cli.py`:

```python
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "catalog/skills/launch-work/scripts/run-lifecycle-extensions.py"


def _write(path: Path, content: str = "x", executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class CliDiscoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        # Isolate XDG so user-installed extensions don't leak in.
        self.env = os.environ.copy()
        self.env["XDG_CONFIG_HOME"] = str(self.root / "xdg-empty")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_discover_emits_json_with_files_and_warnings(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hooks/pre"
        _write(d / "10-first.sh", executable=True)
        _write(d / "no-prefix.sh", executable=True)

        result = subprocess.run(
            [
                str(CLI),
                "discover",
                "--repo-root",
                str(self.repo),
                "--skill",
                "launch-work",
                "--kind",
                "hooks",
                "--position",
                "pre",
            ],
            capture_output=True,
            text=True,
            env=self.env,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(
            [Path(p).name for p in payload["files"]],
            ["10-first.sh"],
        )
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertIn("no-prefix.sh", payload["warnings"][0])
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_cli.py -v`
Expected: FAIL — script does not exist (FileNotFoundError or non-zero exit).

- [ ] **Step 3: Create the CLI shim**

Create `catalog/skills/launch-work/scripts/run-lifecycle-extensions.py`:

```python
#!/usr/bin/env python3
"""CLI front end for project extensions discovery and hook execution.

Subcommands:
    discover    List extensions in execution order as JSON.
    run-hooks   Execute hooks at a position with the env-var protocol.

The importable logic lives in lifecycle_extensions.py beside this script.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_module():
    path = SCRIPT_DIR / "lifecycle_extensions.py"
    spec = importlib.util.spec_from_file_location("lifecycle_extensions", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cmd_discover(args: argparse.Namespace) -> int:
    lifecycle_extensions = _load_module()
    result = lifecycle_extensions.discover(
        repo_root=Path(args.repo_root).resolve(),
        skill=args.skill,
        kind=args.kind,
        position=args.position,
    )
    json.dump(
        {
            "files": [str(p) for p in result.files],
            "warnings": result.warnings,
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_disc = sub.add_parser("discover", help="list extensions as JSON")
    p_disc.add_argument("--repo-root", required=True)
    p_disc.add_argument("--skill", required=True, choices=["launch-work", "land-work"])
    p_disc.add_argument("--kind", required=True, choices=["hooks", "actions"])
    p_disc.add_argument("--position", required=True, choices=["pre", "post"])
    p_disc.set_defaults(func=_cmd_discover)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:

```bash
chmod +x catalog/skills/launch-work/scripts/run-lifecycle-extensions.py
```

- [ ] **Step 4: Run the test, confirm it passes**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add catalog/skills/launch-work/scripts/run-lifecycle-extensions.py tests/launch_work/test_lifecycle_extensions_cli.py
git commit -m "feat(extensions): add CLI with discover subcommand (bento-5v2)"
```

---

## Task 3: `run-hooks` subcommand — env protocol, exit codes, TTY, timeout, advisory

**Files:**
- Modify: `catalog/skills/launch-work/scripts/lifecycle_extensions.py`
- Modify: `catalog/skills/launch-work/scripts/run-lifecycle-extensions.py`
- Test: `tests/launch_work/test_lifecycle_extensions_run_hooks.py`

- [ ] **Step 1: Write the failing test for the happy path**

Create `tests/launch_work/test_lifecycle_extensions_run_hooks.py`:

```python
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "catalog/skills/launch-work/scripts/run-lifecycle-extensions.py"


def _write_hook(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class RunHooksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = os.environ.copy()
        self.env["XDG_CONFIG_HOME"] = str(self.root / "xdg-empty")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _base_args(self, position: str = "pre", advisory: bool = False) -> list[str]:
        args = [
            str(CLI),
            "run-hooks",
            "--repo-root",
            str(self.repo),
            "--skill",
            "launch-work",
            "--position",
            position,
            "--branch",
            "test-branch",
            "--worktree",
            str(self.repo),
            "--base-ref",
            "main",
            "--runtime",
            "claude",
        ]
        if advisory:
            args.append("--advisory")
        return args

    def test_all_hooks_pass_returns_zero(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hooks/pre"
        _write_hook(d / "10-first.sh", "echo first\nexit 0\n")
        _write_hook(d / "20-second.sh", "echo second\nexit 0\n")

        result = subprocess.run(
            self._base_args(), capture_output=True, text=True, env=self.env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("first", result.stdout)
        self.assertIn("second", result.stdout)
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_run_hooks.py -v`
Expected: FAIL — `run-hooks` is not a known subcommand.

- [ ] **Step 3: Implement run_hooks in the importable module**

Append to `catalog/skills/launch-work/scripts/lifecycle_extensions.py`:

```python
import subprocess
import sys
from typing import Optional


HUMAN_HANDOFF_EXIT = 75


@dataclass
class HookContext:
    repo_root: Path
    skill: str
    position: str
    branch: str = ""
    worktree: str = ""
    base_ref: str = ""
    base_sha: str = ""
    head_sha: str = ""
    merge_sha: str = ""
    landed: str = ""
    runtime: str = "unknown"
    task_id: str = ""
    timeout: str = ""


def build_hook_env(ctx: HookContext, parent_env: dict[str, str]) -> dict[str, str]:
    env = dict(parent_env)
    env["BENTO_HOOK_PHASE"] = ctx.skill
    env["BENTO_HOOK_POSITION"] = ctx.position
    env["BENTO_HOOK_REPO_ROOT"] = str(ctx.repo_root)
    env["BENTO_HOOK_WORKTREE"] = ctx.worktree
    env["BENTO_HOOK_BRANCH"] = ctx.branch
    env["BENTO_HOOK_BASE_REF"] = ctx.base_ref
    env["BENTO_HOOK_BASE_SHA"] = ctx.base_sha
    env["BENTO_HOOK_HEAD_SHA"] = ctx.head_sha
    env["BENTO_HOOK_MERGE_SHA"] = ctx.merge_sha
    env["BENTO_HOOK_LANDED"] = ctx.landed
    env["BENTO_HOOK_RUNTIME"] = ctx.runtime
    env["BENTO_HOOK_TASK_ID"] = ctx.task_id
    env["BENTO_HOOK_TTY"] = "1" if sys.stdin.isatty() else "0"
    env["BENTO_HOOK_TIMEOUT"] = ctx.timeout
    env["BENTO_HOOK_REQUIRES_HUMAN"] = str(HUMAN_HANDOFF_EXIT)
    return env


@dataclass
class HookOutcome:
    path: Path
    returncode: int
    timed_out: bool = False


def run_hooks(
    hooks: list[Path],
    ctx: HookContext,
    advisory: bool,
    cwd: Path,
    parent_env: dict[str, str],
) -> tuple[int, list[HookOutcome]]:
    """Run hooks in order. Returns (overall_exit, per-hook outcomes).

    overall_exit is:
      0 if all passed (or advisory mode);
      75 if any hook returned 75 (non-advisory);
      other non-zero if any hook failed (non-advisory).

    In advisory mode the loop continues past failures; the caller is expected
    to surface the messages without halting.
    """
    env = build_hook_env(ctx, parent_env)
    outcomes: list[HookOutcome] = []

    timeout_seconds: Optional[float] = None
    if ctx.timeout:
        try:
            timeout_seconds = float(ctx.timeout)
        except ValueError:
            timeout_seconds = None

    overall = 0
    for hook in hooks:
        try:
            proc = subprocess.run(
                [str(hook)],
                cwd=str(cwd),
                env=env,
                timeout=timeout_seconds,
                check=False,
            )
            outcome = HookOutcome(path=hook, returncode=proc.returncode)
        except subprocess.TimeoutExpired:
            outcome = HookOutcome(path=hook, returncode=124, timed_out=True)

        outcomes.append(outcome)

        if outcome.returncode != 0 and not advisory:
            overall = outcome.returncode
            break

    return overall, outcomes
```

Replace the previous `import os` line at the top of the module if `subprocess` and `sys` aren't already imported; consolidate the imports near the top.

- [ ] **Step 4: Wire run-hooks into the CLI**

Modify `catalog/skills/launch-work/scripts/run-lifecycle-extensions.py`. Add the subparser and command function:

```python
def _cmd_run_hooks(args: argparse.Namespace) -> int:
    lifecycle_extensions = _load_module()
    result = lifecycle_extensions.discover(
        repo_root=Path(args.repo_root).resolve(),
        skill=args.skill,
        kind="hooks",
        position=args.position,
    )
    for warning in result.warnings:
        print(f"[run-lifecycle-extensions] WARNING: {warning}", file=sys.stderr)

    ctx = lifecycle_extensions.HookContext(
        repo_root=Path(args.repo_root).resolve(),
        skill=args.skill,
        position=args.position,
        branch=args.branch,
        worktree=args.worktree,
        base_ref=args.base_ref,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        merge_sha=args.merge_sha,
        landed=args.landed,
        runtime=args.runtime,
        task_id=args.task_id,
        timeout=args.timeout,
    )

    cwd = Path(args.worktree) if args.worktree else Path(args.repo_root)
    import os as _os
    overall, outcomes = lifecycle_extensions.run_hooks(
        hooks=result.files,
        ctx=ctx,
        advisory=args.advisory,
        cwd=cwd,
        parent_env=_os.environ.copy(),
    )

    for outcome in outcomes:
        marker = "OK" if outcome.returncode == 0 else (
            "TIMEOUT" if outcome.timed_out else f"EXIT {outcome.returncode}"
        )
        print(
            f"[run-lifecycle-extensions] {outcome.path.name}: {marker}",
            file=sys.stderr,
        )

    return overall
```

Add the subparser inside `main()`:

```python
    p_run = sub.add_parser("run-hooks", help="execute hooks at a position")
    p_run.add_argument("--repo-root", required=True)
    p_run.add_argument("--skill", required=True, choices=["launch-work", "land-work"])
    p_run.add_argument("--position", required=True, choices=["pre", "post"])
    p_run.add_argument("--branch", default="")
    p_run.add_argument("--worktree", default="")
    p_run.add_argument("--base-ref", default="")
    p_run.add_argument("--base-sha", default="")
    p_run.add_argument("--head-sha", default="")
    p_run.add_argument("--merge-sha", default="")
    p_run.add_argument("--landed", default="")
    p_run.add_argument("--runtime", default="unknown")
    p_run.add_argument("--task-id", default="")
    p_run.add_argument("--timeout", default="")
    p_run.add_argument("--advisory", action="store_true")
    p_run.set_defaults(func=_cmd_run_hooks)
```

- [ ] **Step 5: Run the happy-path test, confirm it passes**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_run_hooks.py -v`
Expected: PASS — `test_all_hooks_pass_returns_zero`.

- [ ] **Step 6: Add tests for failure modes**

Append to `tests/launch_work/test_lifecycle_extensions_run_hooks.py`:

```python
    def test_first_failure_aborts_and_returns_exit_code(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hooks/pre"
        _write_hook(d / "10-fail.sh", "echo bad\nexit 7\n")
        _write_hook(d / "20-never.sh", "echo should-not-run\nexit 0\n")

        result = subprocess.run(
            self._base_args(), capture_output=True, text=True, env=self.env
        )
        self.assertEqual(result.returncode, 7)
        self.assertIn("bad", result.stdout)
        self.assertNotIn("should-not-run", result.stdout)

    def test_human_handoff_exit_75(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hooks/pre"
        _write_hook(d / "10-handoff.sh", "echo need-human\nexit 75\n")

        result = subprocess.run(
            self._base_args(), capture_output=True, text=True, env=self.env
        )
        self.assertEqual(result.returncode, 75)
        self.assertIn("need-human", result.stdout)

    def test_advisory_mode_returns_zero_on_failure(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/land-work/hooks/post"
        _write_hook(d / "10-warn.sh", "echo warning\nexit 3\n")
        _write_hook(d / "20-also.sh", "echo continues\nexit 0\n")

        args = [
            str(CLI),
            "run-hooks",
            "--repo-root",
            str(self.repo),
            "--skill",
            "land-work",
            "--position",
            "post",
            "--branch",
            "feature",
            "--worktree",
            str(self.repo),
            "--advisory",
        ]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("warning", result.stdout)
        self.assertIn("continues", result.stdout)

    def test_env_vars_present_in_hook(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hooks/pre"
        body = (
            "echo PHASE=$BENTO_HOOK_PHASE\n"
            "echo POSITION=$BENTO_HOOK_POSITION\n"
            "echo BRANCH=$BENTO_HOOK_BRANCH\n"
            "echo HUMAN=$BENTO_HOOK_REQUIRES_HUMAN\n"
            "exit 0\n"
        )
        _write_hook(d / "10-env.sh", body)

        result = subprocess.run(
            self._base_args(), capture_output=True, text=True, env=self.env, check=True
        )
        self.assertIn("PHASE=launch-work", result.stdout)
        self.assertIn("POSITION=pre", result.stdout)
        self.assertIn("BRANCH=test-branch", result.stdout)
        self.assertIn("HUMAN=75", result.stdout)

    def test_timeout_kills_hung_hook(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/launch-work/hooks/pre"
        _write_hook(d / "10-hang.sh", "sleep 5\nexit 0\n")

        args = self._base_args() + ["--timeout", "1"]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 124)
        self.assertIn("TIMEOUT", result.stderr)
```

- [ ] **Step 7: Run all run-hooks tests**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_run_hooks.py -v`
Expected: PASS — five tests green.

- [ ] **Step 8: Commit**

```bash
git add catalog/skills/launch-work/scripts/lifecycle_extensions.py catalog/skills/launch-work/scripts/run-lifecycle-extensions.py tests/launch_work/test_lifecycle_extensions_run_hooks.py
git commit -m "feat(extensions): add run-hooks with env protocol, advisory mode, and timeout (bento-5v2)"
```

---

## Task 4: Rewrite `project-hooks.md`

**Files:**
- Modify: `catalog/skills/launch-work/references/project-hooks.md`

This is documentation only. There are no automated tests; verification is a careful read.

- [ ] **Step 1: Replace the file in full**

Replace the entire contents of `catalog/skills/launch-work/references/project-hooks.md` with:

````markdown
# Project Hook Contract

Use this reference when `launch-work` or `land-work` needs to run
project-supplied executable hooks. Hooks are optional: projects without any
matching executable hook files behave exactly as if no hooks were configured.

## Layout

Hooks live under one of these roots, in order of precedence:

1. `<repo-root>/.agent-plugins/bento/bento/`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/`
3. `~/.config/agent-plugins/bento/bento/` when `XDG_CONFIG_HOME` is unset

Within each root, hooks are organized by skill, then kind, then position:

```
<root>/<skill>/hooks/<position>/<two-digit>-<slug>.<ext>
```

- `<skill>` is `launch-work` or `land-work`
- `<position>` is `pre` or `post`
- `<two-digit>-<slug>` is the filename convention; the prefix is required and
  the slug is freeform
- `<ext>` is any executable type (`.sh`, `.py`, no extension, etc.); only the
  executable bit matters

## When hooks fire

| Skill | Position | Fires at | Worktree state |
|---|---|---|---|
| launch-work | pre | After worktree verify, before deps install | Linked worktree exists |
| launch-work | post | After ready-to-land checkpoint, before skill returns | Linked worktree exists |
| land-work | pre | Before merge preview/rebase/merge | Feature-branch worktree |
| land-work | post | After merge succeeds, before skill returns | Feature-branch worktree |

## Filename convention

Each hook filename **must** start with two decimal digits and a hyphen:
`<two-digit>-<slug>`. Files are sorted by ascending numeric prefix; ties
break by lexicographic filename order. Leave gaps (10, 20, 30…) so later
additions can slot between existing hooks without renumbering. Files that
don't match the prefix convention are ignored with a warning.

Hidden files (leading dot), editor backups (`~`, `.bak`, `.swp`, `.orig`),
and non-executable files are silently ignored.

## Discovery and execution

The skill invokes:

```
catalog/skills/launch-work/scripts/run-lifecycle-extensions.py run-hooks \
  --repo-root <repo> --skill <skill> --position <pre|post> \
  --branch <branch> --worktree <worktree> ...
```

Hooks at a position run sequentially. The first non-zero exit halts further
hooks at that position (except in advisory mode — see below).

The working directory is the linked worktree (launch-work) or feature-branch
worktree (land-work).

## Environment

| Variable | Meaning |
|---|---|
| `BENTO_HOOK_PHASE` | `launch-work` or `land-work` |
| `BENTO_HOOK_POSITION` | `pre` or `post` |
| `BENTO_HOOK_REPO_ROOT` | Absolute repo root |
| `BENTO_HOOK_WORKTREE` | Absolute worktree path |
| `BENTO_HOOK_BRANCH` | Current task or feature branch |
| `BENTO_HOOK_BASE_REF` | Primary-branch ref name |
| `BENTO_HOOK_BASE_SHA` | SHA of base ref when known |
| `BENTO_HOOK_HEAD_SHA` | SHA of feature-branch head when known |
| `BENTO_HOOK_MERGE_SHA` | Merge commit SHA; set only at `land-work/post` |
| `BENTO_HOOK_LANDED` | `1` only at `land-work/post` once merge is complete |
| `BENTO_HOOK_RUNTIME` | `claude`, `codex`, or `unknown` |
| `BENTO_HOOK_TASK_ID` | Tracker item ID when available |
| `BENTO_HOOK_TTY` | `1` if stdin is a TTY, else `0` |
| `BENTO_HOOK_TIMEOUT` | Seconds, or empty for no timeout |
| `BENTO_HOOK_REQUIRES_HUMAN` | `75` |

Unavailable values are set to empty strings, not omitted.

## Exit codes

- `0` — pass; continue.
- `75` (`EX_TEMPFAIL`) — human handoff. Halt, preserve branch and linked
  worktree, surface stdout as the handoff message, do not perform
  destructive cleanup.
- Any other non-zero — failure. Halt, surface stdout and stderr, preserve
  branch and linked worktree.

### Advisory mode (`land-work/post` only)

After a successful merge, abort cannot reverse the landing. The skill runs
`land-work/post` hooks in advisory mode: non-zero exits surface the
message but do not unwind the merge or block tracker mutations. Continue
running remaining hooks past a failure.

## Timeouts

There is no built-in timeout. Interactive hooks (`gh auth login`,
passphrase prompts) work without ceremony. The agent surfaces a soft
heartbeat message after long quiet stretches; Ctrl-C reaches the running
hook directly.

A repo that wants a bounded run sets `BENTO_HOOK_TIMEOUT=<seconds>` (e.g.,
in repo-local environment for CI). Default unset means no timeout. Hooks
that exceed the timeout are killed and reported with exit code `124`.

Hooks that need to detect a non-interactive context can check
`BENTO_HOOK_TTY`:

```sh
#!/bin/sh
if [ "$BENTO_HOOK_TTY" != "1" ]; then
  echo "This hook needs an interactive terminal."
  exit "$BENTO_HOOK_REQUIRES_HUMAN"
fi
exec gh auth login
```

## Reference examples

No-op:

```sh
#!/bin/sh
exit 0
```

Human-handoff:

```sh
#!/bin/sh
cat <<'MESSAGE'
Human review required before this branch can land.
Review the generated artifacts, then rerun land-work.
MESSAGE
exit "${BENTO_HOOK_REQUIRES_HUMAN:-75}"
```

Conditional based on phase and position:

```sh
#!/bin/sh
case "$BENTO_HOOK_PHASE/$BENTO_HOOK_POSITION" in
  launch-work/pre)  echo "post-bootstrap check"; exit 0 ;;
  launch-work/post) echo "ready-to-land sanity check"; exit 0 ;;
  *)                exit 0 ;;
esac
```
````

- [ ] **Step 2: Verify the file by re-reading it**

Read the file and confirm: header structure clear, four-row position table accurate, env table includes the new vars, advisory section present, no references to legacy paths or `main` position.

- [ ] **Step 3: Commit**

```bash
git add catalog/skills/launch-work/references/project-hooks.md
git commit -m "docs(extensions): rewrite project-hooks.md for new layout, prefix convention, and advisory mode (bento-5v2)"
```

---

## Task 5: Add `project-actions.md`

**Files:**
- Create: `catalog/skills/launch-work/references/project-actions.md`

- [ ] **Step 1: Create the file**

Write `catalog/skills/launch-work/references/project-actions.md`:

````markdown
# Project Action Contract

Use this reference when `launch-work` or `land-work` needs to apply
project-supplied prose actions. Actions are markdown files the agent reads
and applies as additive guidance — distinct from hooks (executables that
gate). Actions are optional.

## Layout

Actions live in the same XDG-precedence chain as hooks:

1. `<repo-root>/.agent-plugins/bento/bento/`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/`
3. `~/.config/agent-plugins/bento/bento/`

Within each root:

```
<root>/<skill>/actions/<position>/<two-digit>-<slug>.md
```

- `<skill>` is `launch-work` or `land-work`
- `<position>` is `pre` or `post`

Actions deliberately do not have a slot mid-skill. Mid-skill is hook
territory (deterministic gates that can abort). Actions stay at boundaries.

## When actions fire

Same per-skill timings as hooks. At each position, **hooks run first**; if
all hooks pass (exit 0), the agent reads action files in numeric-prefix
order and applies each before moving to the next.

If any hook returns non-zero (other than in advisory mode at
`land-work/post`), actions for that position do not load.

## Filename convention

Same as hooks. Two-digit numeric prefix required:
`<two-digit>-<slug>.md`. Files without the prefix are ignored with a
warning. Files with extensions other than `.md` are ignored silently.

## Authoring shape

A typical action file:

```markdown
# Action title (optional H1)

## Context

Optional. Describe what state the action assumes (e.g., "linked worktree
exists; progress log is at worktree-ready").

## Body

Plain prose telling the agent what additional rules to apply for the rest
of this position's work. Actions are *additive* and may *modify* default
behavior. They must not direct full replacement of the skill's built-in
workflow.

## Stop conditions

Optional. A list of predicates the agent evaluates at apply time. If any
match, the agent halts, surfaces the matched condition, and preserves
branch and linked worktree (mirroring exit-75 semantics for hooks).

- Predicate one (in plain language; agent uses tools to verify)
- Predicate two
```

The `## Stop conditions` section name is the only structured convention.
Everything else is free-form markdown.

## Advisory mode (`land-work/post` only)

After a successful merge, halt cannot reverse the landing. Stop conditions
matched at `land-work/post` are advisory: the agent surfaces the matched
condition but does not unwind the merge or block tracker mutations.
Subsequent actions continue to apply.

## Discovery

The skill invokes:

```
catalog/skills/launch-work/scripts/run-lifecycle-extensions.py discover \
  --repo-root <repo> --skill <skill> --kind actions --position <pre|post>
```

The output is a JSON list of file paths in execution order, plus any
warnings (e.g., missing-prefix filenames). The agent reads each file in
order and applies it.

## Reference example

`30-warn-on-uncommitted-config.md`:

````markdown
# Warn on uncommitted config

## Context

Assumes the linked worktree exists. Applied at `launch-work/post`.

## Body

Before reporting that the work is ready to land, run `git status -s` in
the worktree and surface any tracked configuration files (e.g.,
`config/*.yaml`, `.env.example`) that have uncommitted modifications. Do
not block; this is a soft prompt for the user to confirm intent.

## Stop conditions

- The repository contains a `LICENSE.draft` file at the repo root. Verify
  with `test -f "$BENTO_HOOK_REPO_ROOT/LICENSE.draft"`.
````
````

- [ ] **Step 2: Re-read and verify**

Confirm the file describes: layout, timings, filename convention, authoring
shape, stop conditions, advisory mode, the discover invocation, and one
example. No references to a `main` position.

- [ ] **Step 3: Commit**

```bash
git add catalog/skills/launch-work/references/project-actions.md
git commit -m "docs(extensions): add project-actions.md contract for prose actions (bento-5v2)"
```

---

## Task 6: Wire `launch-work/SKILL.md`

**Files:**
- Modify: `catalog/skills/launch-work/SKILL.md`

- [ ] **Step 1: Read the current file**

Open `catalog/skills/launch-work/SKILL.md` and locate step `9a` (the existing
single-moment project-hook step) and the surrounding workflow.

- [ ] **Step 2: Replace step 9a with a `pre`-position invocation**

Replace step `9a` with:

```markdown
9a. Read `launch-work/references/project-hooks.md` and
    `launch-work/references/project-actions.md`. Run the **`pre`** extensions
    after worktree verification and before dependency installation:

    ```bash
    launch-work/scripts/run-lifecycle-extensions.py run-hooks \
      --repo-root <repo-root> \
      --skill launch-work \
      --position pre \
      --branch <branch> \
      --worktree <worktree> \
      --base-ref <primary-branch> \
      --runtime claude
    ```

    Then discover and apply prose actions for the `pre` position:

    ```bash
    launch-work/scripts/run-lifecycle-extensions.py discover \
      --repo-root <repo-root> \
      --skill launch-work \
      --kind actions \
      --position pre
    ```

    Read each listed file in order. Treat any `## Stop conditions` predicate
    as a halt signal. If a hook exited non-zero, follow the contract's
    abort or human-handoff semantics; actions do not load in that case.
```

- [ ] **Step 3: Add a `post`-position step before the final summary**

Locate the workflow step that updates the log to `ready-to-land` (the last
checkpoint update, currently in step 11). Add a new step between
`ready-to-land` and the final task summary:

```markdown
11a. Run the **`post`** extensions before declaring the work ready to land:

    ```bash
    launch-work/scripts/run-lifecycle-extensions.py run-hooks \
      --repo-root <repo-root> \
      --skill launch-work \
      --position post \
      --branch <branch> \
      --worktree <worktree> \
      --base-ref <primary-branch> \
      --head-sha $(git rev-parse HEAD) \
      --runtime claude
    ```

    Then discover and apply `post` prose actions:

    ```bash
    launch-work/scripts/run-lifecycle-extensions.py discover \
      --repo-root <repo-root> \
      --skill launch-work \
      --kind actions \
      --position post
    ```

    Read each listed file in order. Apply additive guidance and evaluate
    `## Stop conditions` predicates. If a hook or action halts, preserve
    branch and linked worktree and surface the message.
```

- [ ] **Step 4: Update the Non-Negotiable Rules block**

Replace the existing project-hooks bullet:

```markdown
- Do not skip discovered project hooks. A `75` exit code is a human handoff,
  not a destructive failure; preserve the branch and linked worktree and
  surface the hook's stdout.
```

with:

```markdown
- Do not skip discovered project hooks or actions at the `pre` and `post`
  positions. A `75` exit code (hooks) or matched `## Stop conditions`
  predicate (actions) is a human handoff, not a destructive failure;
  preserve the branch and linked worktree and surface the message.
```

- [ ] **Step 5: Re-read the file and verify the new flow**

Confirm: step 9a calls `run-lifecycle-extensions.py run-hooks` and `discover` for
`pre`; step 11a does the same for `post`; non-negotiable rules cover both
positions; no remaining references to `project-hooks.md` as a single mid-skill
moment.

- [ ] **Step 6: Commit**

```bash
git add catalog/skills/launch-work/SKILL.md
git commit -m "feat(launch-work): invoke extensions at pre and post positions (bento-5v2)"
```

---

## Task 7: Wire `land-work/SKILL.md`

**Files:**
- Modify: `catalog/skills/land-work/SKILL.md`

- [ ] **Step 1: Read the current file**

Open `catalog/skills/land-work/SKILL.md` and locate step `2a` (the existing
single-moment project-hook step).

- [ ] **Step 2: Replace step 2a with a `pre`-position invocation**

Replace step `2a` with:

```markdown
2a. Read `../launch-work/references/project-hooks.md` and
    `../launch-work/references/project-actions.md`. Run the **`pre`**
    extensions before creating or verifying the merge preview, rebasing, or
    merging:

    ```bash
    ../launch-work/scripts/run-lifecycle-extensions.py run-hooks \
      --repo-root <repo-root> \
      --skill land-work \
      --position pre \
      --branch <feature-branch> \
      --worktree <feature-worktree> \
      --base-ref <primary-branch> \
      --base-sha <leased-sha> \
      --head-sha $(git rev-parse HEAD) \
      --runtime claude
    ```

    Then discover and apply `pre` prose actions:

    ```bash
    ../launch-work/scripts/run-lifecycle-extensions.py discover \
      --repo-root <repo-root> \
      --skill land-work \
      --kind actions \
      --position pre
    ```

    Read each listed file in order and apply. If a hook exits non-zero or a
    `## Stop conditions` predicate matches, halt; the merge has not started.
```

- [ ] **Step 3: Add a `post`-position step after the merge succeeds**

Locate step 9 (closing or updating the tracker after the merge succeeds).
Insert a new step `8a` between the verified-landing step (currently 8 or
end-of-step-8) and the tracker close (step 9):

```markdown
8a. Run the **`post`** extensions in **advisory mode** (the merge has
    already succeeded; abort cannot reverse it):

    ```bash
    ../launch-work/scripts/run-lifecycle-extensions.py run-hooks \
      --repo-root <repo-root> \
      --skill land-work \
      --position post \
      --advisory \
      --branch <feature-branch> \
      --worktree <feature-worktree> \
      --base-ref <primary-branch> \
      --base-sha <new-base-sha> \
      --merge-sha $(git rev-parse <primary-branch>) \
      --landed 1 \
      --runtime claude
    ```

    Then discover and apply `post` prose actions (also advisory):

    ```bash
    ../launch-work/scripts/run-lifecycle-extensions.py discover \
      --repo-root <repo-root> \
      --skill land-work \
      --kind actions \
      --position post
    ```

    Surface any non-zero hook exits or matched `## Stop conditions`
    predicates to the user as warnings; do not unwind the merge, do not
    block tracker mutations.
```

- [ ] **Step 4: Update the Non-Negotiable Rules block**

Replace the existing project-hooks bullet (currently: "Do not skip
discovered project hooks…") with:

```markdown
- Do not skip discovered project hooks or actions at the `pre` and `post`
  positions. At `pre`, a `75` exit (hooks) or matched stop condition
  (actions) halts before the merge starts and is a human handoff. At
  `post`, both are advisory: surface the message and continue.
```

- [ ] **Step 5: Re-read and verify**

Confirm: step 2a uses `pre`, step 8a uses `post --advisory`, the `--advisory`
flag is present only at `post`, env arguments include `--merge-sha` and
`--landed 1` at `post`, non-negotiable rules cover both positions.

- [ ] **Step 6: Commit**

```bash
git add catalog/skills/land-work/SKILL.md
git commit -m "feat(land-work): invoke extensions at pre and post (advisory) positions (bento-5v2)"
```

---

## Task 8: Integration scenario test

**Files:**
- Test: `tests/launch_work/test_lifecycle_extensions_integration.py`

This test wires up the discover + run-hooks calls together and confirms the
end-to-end behavior the SKILL.md prose describes.

- [ ] **Step 1: Write the integration test**

Create `tests/launch_work/test_lifecycle_extensions_integration.py`:

```python
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "catalog/skills/launch-work/scripts/run-lifecycle-extensions.py"


def _write(path: Path, content: str = "x", executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class IntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.env = os.environ.copy()
        self.env["XDG_CONFIG_HOME"] = str(self.root / "xdg-empty")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pre_pass_then_actions_discoverable(self) -> None:
        # A passing pre hook
        hook_dir = self.repo / ".agent-plugins/bento/bento/launch-work/hooks/pre"
        _write(
            hook_dir / "10-ok.sh",
            "#!/bin/sh\necho pre-ok\nexit 0\n",
            executable=True,
        )
        # Two prose actions in order
        action_dir = self.repo / ".agent-plugins/bento/bento/launch-work/actions/pre"
        _write(action_dir / "10-first.md", "# First action\n\n## Body\nDo X.\n")
        _write(action_dir / "20-second.md", "# Second action\n\n## Body\nDo Y.\n")

        run_args = [
            str(CLI), "run-hooks",
            "--repo-root", str(self.repo),
            "--skill", "launch-work",
            "--position", "pre",
            "--branch", "test", "--worktree", str(self.repo),
        ]
        run = subprocess.run(run_args, capture_output=True, text=True, env=self.env)
        self.assertEqual(run.returncode, 0, run.stderr)

        disc_args = [
            str(CLI), "discover",
            "--repo-root", str(self.repo),
            "--skill", "launch-work",
            "--kind", "actions",
            "--position", "pre",
        ]
        disc = subprocess.run(
            disc_args, capture_output=True, text=True, env=self.env, check=True
        )
        payload = json.loads(disc.stdout)
        self.assertEqual(
            [Path(p).name for p in payload["files"]],
            ["10-first.md", "20-second.md"],
        )

    def test_post_advisory_continues_past_failure(self) -> None:
        d = self.repo / ".agent-plugins/bento/bento/land-work/hooks/post"
        _write(
            d / "10-fails.sh",
            "#!/bin/sh\necho first-failed\nexit 5\n",
            executable=True,
        )
        _write(
            d / "20-runs.sh",
            "#!/bin/sh\necho second-ran\nexit 0\n",
            executable=True,
        )

        args = [
            str(CLI), "run-hooks",
            "--repo-root", str(self.repo),
            "--skill", "land-work",
            "--position", "post",
            "--advisory",
            "--branch", "feature", "--worktree", str(self.repo),
            "--landed", "1",
        ]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("first-failed", result.stdout)
        self.assertIn("second-ran", result.stdout)

    def test_no_extensions_present_returns_zero(self) -> None:
        args = [
            str(CLI), "run-hooks",
            "--repo-root", str(self.repo),
            "--skill", "launch-work",
            "--position", "pre",
            "--branch", "x", "--worktree", str(self.repo),
        ]
        result = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0)
```

- [ ] **Step 2: Run the integration tests**

Run: `python -m pytest tests/launch_work/test_lifecycle_extensions_integration.py -v`
Expected: PASS — three tests green.

- [ ] **Step 3: Run the full lifecycle extensions test set as a final sanity pass**

Run:
```bash
python -m pytest tests/launch_work/test_lifecycle_extensions_discover.py \
  tests/launch_work/test_lifecycle_extensions_cli.py \
  tests/launch_work/test_lifecycle_extensions_run_hooks.py \
  tests/launch_work/test_lifecycle_extensions_integration.py -v
```
Expected: all green.

- [ ] **Step 4: Run the repo's full test suite to confirm no regressions**

Run: `python -m pytest tests/ -q`
Expected: all green. If any test outside the new files fails, investigate
before committing — this design should not affect existing behavior.

- [ ] **Step 5: Commit**

```bash
git add tests/launch_work/test_lifecycle_extensions_integration.py
git commit -m "test(extensions): add integration tests for pre/post + advisory + no-extensions cases (bento-5v2)"
```

---

## Verification summary

After all eight tasks:

- Six new files: `lifecycle_extensions.py`, `run-lifecycle-extensions.py`, four test files, `project-actions.md`.
- Three modified files: `project-hooks.md`, `launch-work/SKILL.md`, `land-work/SKILL.md`.
- ~25 new test cases covering discovery, ordering, exclusions, env protocol, exit codes, advisory mode, timeout, and integration.
- No behavioral change for repos with no hooks/actions configured.
- No backwards-compatibility code: the new layout is the only layout supported.

The two motivating extensions can now be authored as:

- **After launch-work** → `<repo>/.agent-plugins/bento/bento/launch-work/actions/post/10-<slug>.md`
- **Before land-work** → `<repo>/.agent-plugins/bento/bento/land-work/actions/pre/10-<slug>.md`
