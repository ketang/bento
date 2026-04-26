# /handoff Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the bento `/handoff` skill — a deterministic helper plus SKILL.md prose that writes a structured session-reboot prompt under `/tmp/`, resolved through the agent-plugins convention's repo → home → bundled lookup chain, plus the install-time and session-time seeding mechanisms that put the bundled default into the user's home-scope agent-plugins directory.

**Architecture:** New skill at `catalog/skills/handoff/` with a Python helper `scripts/handoff.py` and a bundled markdown template `references/templates/handoff.md`. Three independent seed paths populate the home-scope template: (1) a SessionStart hook in the bento Claude plugin (`catalog/hooks/bento/scripts/seed-agent-plugins.py`), (2) a step in `install/_codex-installer-lib.sh` that runs after plugin placement, (3) a self-heal in `handoff.py`. Expedition detection is delegated to `expedition.py discover` via subprocess; primary-branch detection reuses `git_state.detect_primary_branch`.

**Tech Stack:** Python 3 (stdlib only — no third-party deps), Bash for the Codex installer, JSON for hook wiring, Markdown for SKILL.md and the template. Tests use Python's `unittest` with `tempfile.TemporaryDirectory` and live `git` invocations under each fixture.

---

## File Structure

Files to create:

- `catalog/skills/handoff/SKILL.md` — agent-facing skill prose (frontmatter + body, target ≤ 250 lines).
- `catalog/skills/handoff/scripts/handoff.py` — Python 3 helper. Owns preconditions, suffix derivation, template resolution, self-heal, path generation, file write.
- `catalog/skills/handoff/scripts/git_state.py` — copy of the existing helper module from `catalog/skills/expedition/scripts/git_state.py`, kept as a sibling so `handoff.py` can import it without sys.path manipulation. (The launch-work skill follows this same convention — it has its own copy of `git_state.py` rather than reaching across skill boundaries.)
- `catalog/skills/handoff/references/templates/handoff.md` — bundled default template, ≤ 30 lines.
- `catalog/hooks/bento/scripts/seed-agent-plugins.py` — SessionStart hook script. Stat-and-skip semantics; never overwrites; never fatal-errors.
- `tests/test_handoff.py` — unittest module covering preconditions, suffix derivation, template resolution, self-heal, path generation.
- `tests/test_seed_agent_plugins.py` — unittest module for the SessionStart hook (idempotence, no overwrite, permission failure swallowed).

Files to modify:

- `catalog/hooks/bento/hooks.json` — add a `SessionStart` array registering the new seed script alongside the existing `PreToolUse`.
- `scripts/build-plugins` — register the `handoff` skill under the `bento` plugin's `skills` list (around line 84-100, the `PLUGIN_DEFS["bento"]["skills"]` array). Build script's `copy_hooks` already recurses, so the new hook script is picked up without further changes.
- `install/_codex-installer-lib.sh` — add a `seed_agent_plugins_handoff` function and call it after the `for plugin in "${PLUGIN_NAMES[@]}"` placement loop (around line 78), before the marketplace generation block.
- `tests/test_codex_installer.py` — add a test asserting that home-scope and project-scope installs both seed `agent-plugins/bento/bento/handoff/template.md` from the freshly placed plugin bundle, and that re-running the installer is a no-op when the file already exists.
- `catalog/plugin-versions.json` — bumped via `scripts/bump-plugin-versions` (do not hand-edit). The new skill triggers a bump for `bento`.

Generated, not hand-edited:

- `plugins/claude/bento/skills/handoff/...` and `plugins/codex/bento/skills/handoff/...` — produced by `scripts/build-plugins`.
- `plugins/claude/bento/hooks/scripts/seed-agent-plugins.py` and `plugins/claude/bento/hooks/hooks.json` — produced by `scripts/build-plugins`'s `copy_hooks`.
- `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json` — produced by build/install respectively.

No new top-level directories are introduced. The `agent-plugins/bento/bento/handoff/` tree is created at runtime under `$XDG_CONFIG_HOME` or `<repo>/.agent-plugins/`; nothing is checked into this repo at those paths.

---

### Task 1: Bundled default template

**Files:**
- Create: `catalog/skills/handoff/references/templates/handoff.md`

This is intentionally the first task because every later task either reads or seeds this file.

- [ ] **Step 1: Write the file**

Write `catalog/skills/handoff/references/templates/handoff.md` with exactly this content:

```markdown
# Handoff

## Next action

<!-- The single concrete next step for the new session. Imperative tense, one short paragraph. -->

## Original task

<!-- The user's original request that started this session, in one line. -->

## Branch & worktree

<!-- Current branch, worktree path, primary branch. -->

## Verification state

<!-- What was run, what passed, what failed, what was not yet tested. -->

## Decisions & dead-ends

<!-- Non-obvious choices made, approaches ruled out and why. -->

## Pending decisions / blockers

<!-- Questions waiting on the user, external blockers. -->

## Notes

<!-- Free-form prose for in-flight reasoning that does not fit a slot. -->
```

- [ ] **Step 2: Verify the file content**

Run: `wc -l catalog/skills/handoff/references/templates/handoff.md`
Expected: a line count between 25 and 35 (the file as written above is 27 lines).

Run: `grep -c '^## ' catalog/skills/handoff/references/templates/handoff.md`
Expected: `7`

- [ ] **Step 3: Commit**

```bash
git add catalog/skills/handoff/references/templates/handoff.md
git commit -m "feat(handoff): add bundled default template"
```

---

### Task 2: Sibling git_state helper module

The `handoff.py` script needs `detect_checkout_root`, `detect_primary_branch`, and `git` from the existing helper module. Following bento's existing convention (the launch-work skill keeps its own copy under `launch-work/scripts/git_state.py`), copy the file rather than introducing a cross-skill import.

**Files:**
- Create: `catalog/skills/handoff/scripts/git_state.py`

- [ ] **Step 1: Copy the existing module verbatim**

Run: `cp catalog/skills/expedition/scripts/git_state.py catalog/skills/handoff/scripts/git_state.py`

- [ ] **Step 2: Verify the copy**

Run: `diff catalog/skills/launch-work/scripts/git_state.py catalog/skills/handoff/scripts/git_state.py`
Expected: no output (they are byte-identical, both copies of the expedition source).

Run: `python3 -c "import importlib.util, importlib.machinery; loader = importlib.machinery.SourceFileLoader('git_state', 'catalog/skills/handoff/scripts/git_state.py'); spec = importlib.util.spec_from_loader('git_state', loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m); print(m.detect_primary_branch.__name__)"`
Expected: `detect_primary_branch`

- [ ] **Step 3: Commit**

```bash
git add catalog/skills/handoff/scripts/git_state.py
git commit -m "feat(handoff): vendor git_state helper for sibling import"
```

---

### Task 3: handoff.py — argument parsing skeleton

Implement the script bottom-up via TDD. Each step adds one capability with a paired test. Steps 3.1–3.6 finish with the script doing useful work end-to-end.

**Files:**
- Create: `catalog/skills/handoff/scripts/handoff.py`
- Create: `tests/test_handoff.py`

- [ ] **Step 3.1.a: Write the failing test for `--help`**

Append to `tests/test_handoff.py`:

```python
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_SCRIPT = REPO_ROOT / "catalog" / "skills" / "handoff" / "scripts" / "handoff.py"


class HandoffHelpTest(unittest.TestCase):
    def test_help_flag_exits_zero_and_describes_inputs(self) -> None:
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--input", result.stdout)
        self.assertIn("--slug", result.stdout)
        self.assertIn("--verbose", result.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3.1.b: Run the test to confirm it fails**

Run: `python3 -m unittest tests.test_handoff -v`
Expected: FAIL because `handoff.py` does not exist yet (FileNotFoundError or non-zero exit).

- [ ] **Step 3.1.c: Write the minimal `handoff.py` skeleton**

Create `catalog/skills/handoff/scripts/handoff.py` with this content:

```python
#!/usr/bin/env python3
"""Bento /handoff helper.

Writes a markdown handoff prompt to /tmp/ on success. Refuses to write when
preconditions fail (not in a git repo, detached HEAD, or active expedition).
See catalog/skills/handoff/SKILL.md for the runtime contract."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handoff",
        description="Write a structured session-reboot prompt to /tmp/.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="path to a file containing the filled-in template, or '-' for stdin",
    )
    parser.add_argument(
        "--slug",
        help="suffix to use when on the primary branch (kebab-case, 2-4 words)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print extra diagnostics to stderr",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    del args  # placeholder while later steps add behavior
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Then mark it executable:

```bash
chmod +x catalog/skills/handoff/scripts/handoff.py
```

- [ ] **Step 3.1.d: Run the test to confirm it passes**

Run: `python3 -m unittest tests.test_handoff -v`
Expected: PASS.

- [ ] **Step 3.1.e: Commit**

```bash
git add catalog/skills/handoff/scripts/handoff.py tests/test_handoff.py
git commit -m "feat(handoff): add helper skeleton with argparse"
```

---

### Task 4: handoff.py — preconditions

Add the three preconditions (git repo, named branch, no active expedition) one at a time.

- [ ] **Step 4.1.a: Write the failing test for "not in git repo" diagnostic**

Append to `tests/test_handoff.py`:

```python
class HandoffPreconditionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.input_path = self.tmp_path / "body.md"
        self.input_path.write_text("# body\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, cwd: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path), *extra],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_not_in_git_repo_emits_diagnostic_and_writes_no_file(self) -> None:
        non_repo = self.tmp_path / "not-a-repo"
        non_repo.mkdir()
        result = self._run(non_repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not in a git repository", result.stderr)
        self.assertEqual(list((non_repo).iterdir()), [])
```

- [ ] **Step 4.1.b: Run the test to confirm it fails**

Run: `python3 -m unittest tests.test_handoff.HandoffPreconditionsTest.test_not_in_git_repo_emits_diagnostic_and_writes_no_file -v`
Expected: FAIL — current `main()` exits 0 unconditionally.

- [ ] **Step 4.1.c: Implement the precondition**

Edit `catalog/skills/handoff/scripts/handoff.py`. Add at the top of the imports block:

```python
import subprocess
from pathlib import Path
```

Add a helper function above `main`:

```python
def _is_inside_work_tree(cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"
```

Replace the body of `main` with:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cwd = Path.cwd().resolve()
    if not _is_inside_work_tree(cwd):
        print(
            "/handoff: not in a git repository; refusing to write a handoff file.",
            file=sys.stderr,
        )
        return 2
    del args
    return 0
```

- [ ] **Step 4.1.d: Run the test to confirm it passes**

Run: `python3 -m unittest tests.test_handoff.HandoffPreconditionsTest.test_not_in_git_repo_emits_diagnostic_and_writes_no_file -v`
Expected: PASS.

- [ ] **Step 4.2.a: Write the failing test for detached HEAD**

Append to the `HandoffPreconditionsTest` class in `tests/test_handoff.py`:

```python
    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    def _make_repo_with_commit(self) -> Path:
        repo = self.tmp_path / "repo"
        repo.mkdir()
        self._git(repo, "init", "-q", "-b", "main")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test")
        (repo / "README.md").write_text("hi\n", encoding="utf-8")
        self._git(repo, "add", "README.md")
        self._git(repo, "commit", "-q", "-m", "init")
        return repo

    def test_detached_head_emits_diagnostic_and_writes_no_file(self) -> None:
        repo = self._make_repo_with_commit()
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self._git(repo, "checkout", "-q", "--detach", sha)
        existing_before = set(p.name for p in repo.iterdir())
        result = self._run(repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD is detached", result.stderr)
        existing_after = set(p.name for p in repo.iterdir())
        self.assertEqual(existing_before, existing_after)
```

- [ ] **Step 4.2.b: Run the test to confirm it fails**

Run: `python3 -m unittest tests.test_handoff.HandoffPreconditionsTest.test_detached_head_emits_diagnostic_and_writes_no_file -v`
Expected: FAIL — script does not yet check HEAD.

- [ ] **Step 4.2.c: Implement the detached-HEAD precondition**

Edit `handoff.py`. Add helper:

```python
def _has_named_branch(cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "HEAD"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0
```

In `main`, after the `_is_inside_work_tree` block:

```python
    if not _has_named_branch(cwd):
        print(
            "/handoff: HEAD is detached; refusing to write a handoff file. "
            "Check out a named branch.",
            file=sys.stderr,
        )
        return 2
```

- [ ] **Step 4.2.d: Run the test to confirm it passes**

Run: `python3 -m unittest tests.test_handoff.HandoffPreconditionsTest.test_detached_head_emits_diagnostic_and_writes_no_file -v`
Expected: PASS.

- [ ] **Step 4.3.a: Write the failing test for active-expedition refusal**

Append to the `HandoffPreconditionsTest` class:

```python
    def test_active_expedition_emits_diagnostic_and_writes_no_file(self) -> None:
        repo = self._make_repo_with_commit()
        # Stub expedition.py via env override so the helper sees an "active" expedition.
        fake_expedition = self.tmp_path / "fake-expedition.py"
        fake_expedition.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "if 'discover' in sys.argv:\n"
            "    cwd = __import__('os').getcwd()\n"
            "    json.dump({'ok': True, 'expeditions': [{\n"
            "        'expedition': 'demo',\n"
            "        'base_worktree': cwd,\n"
            "        'active_branches': [],\n"
            "        'current_checkout': True,\n"
            "    }]}, sys.stdout)\n"
            "    sys.stdout.write('\\n')\n",
            encoding="utf-8",
        )
        fake_expedition.chmod(0o755)
        env = os.environ.copy()
        env["BENTO_EXPEDITION_SCRIPT"] = str(fake_expedition)
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path)],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active expedition", result.stderr)
        self.assertIn("demo", result.stderr)
```

- [ ] **Step 4.3.b: Run the test to confirm it fails**

Run: `python3 -m unittest tests.test_handoff.HandoffPreconditionsTest.test_active_expedition_emits_diagnostic_and_writes_no_file -v`
Expected: FAIL — script does not yet shell out to expedition.py.

- [ ] **Step 4.3.c: Implement expedition detection**

Edit `handoff.py`. Add imports:

```python
import json
import os
```

Add helpers:

```python
def _expedition_script_path() -> Path:
    override = os.environ.get("BENTO_EXPEDITION_SCRIPT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "expedition" / "scripts" / "expedition.py"


def _active_expedition(cwd: Path) -> str | None:
    script = _expedition_script_path()
    if not script.exists():
        return None
    result = subprocess.run(
        [str(script), "discover"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for entry in payload.get("expeditions", []):
        if entry.get("current_checkout"):
            return str(entry.get("expedition") or "")
    return None
```

In `main`, after the named-branch check:

```python
    expedition_name = _active_expedition(cwd)
    if expedition_name:
        print(
            f"/handoff: active expedition {expedition_name} detected; "
            f"use the expedition skill's session-end protocol instead "
            f"(update docs/expeditions/{expedition_name}/handoff.md via "
            f"expedition/scripts/expedition.py).",
            file=sys.stderr,
        )
        return 2
```

- [ ] **Step 4.3.d: Run the test to confirm it passes**

Run: `python3 -m unittest tests.test_handoff.HandoffPreconditionsTest.test_active_expedition_emits_diagnostic_and_writes_no_file -v`
Expected: PASS.

- [ ] **Step 4.3.e: Run the full preconditions class to confirm no regressions**

Run: `python3 -m unittest tests.test_handoff.HandoffPreconditionsTest -v`
Expected: 3 tests pass.

- [ ] **Step 4.4: Commit**

```bash
git add catalog/skills/handoff/scripts/handoff.py tests/test_handoff.py
git commit -m "feat(handoff): refuse non-repo, detached HEAD, and active expedition"
```

---

### Task 5: handoff.py — suffix derivation

Add suffix derivation for non-primary branches (sanitize) and primary branch (require `--slug`).

**Files:**
- Modify: `catalog/skills/handoff/scripts/handoff.py`
- Modify: `tests/test_handoff.py`

- [ ] **Step 5.1.a: Write the failing tests for suffix derivation**

Append to `tests/test_handoff.py`:

```python
import importlib.machinery
import importlib.util


def _load_handoff_module():
    loader = importlib.machinery.SourceFileLoader("handoff_module", str(HANDOFF_SCRIPT))
    spec = importlib.util.spec_from_loader("handoff_module", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class HandoffSuffixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.handoff = _load_handoff_module()

    def test_clean_branch_name_used_verbatim(self) -> None:
        self.assertEqual(self.handoff.sanitize_suffix("feat-foo"), "feat-foo")

    def test_branch_with_slash_replaced_with_dash(self) -> None:
        self.assertEqual(self.handoff.sanitize_suffix("user/feature"), "user-feature")

    def test_unusual_chars_replaced_with_dash(self) -> None:
        self.assertEqual(
            self.handoff.sanitize_suffix("weird name (test)#1"),
            "weird-name--test--1",
        )

    def test_only_alphanum_dot_underscore_dash_kept(self) -> None:
        self.assertEqual(
            self.handoff.sanitize_suffix("a.b_c-d"),
            "a.b_c-d",
        )
```

- [ ] **Step 5.1.b: Run to confirm failure**

Run: `python3 -m unittest tests.test_handoff.HandoffSuffixTest -v`
Expected: FAIL — `sanitize_suffix` is not defined.

- [ ] **Step 5.1.c: Implement `sanitize_suffix`**

Edit `handoff.py`. Add near the top of the module:

```python
import re

_SUFFIX_VALID = re.compile(r"[A-Za-z0-9._-]")


def sanitize_suffix(branch: str) -> str:
    return "".join(ch if _SUFFIX_VALID.match(ch) else "-" for ch in branch)
```

- [ ] **Step 5.1.d: Run to confirm pass**

Run: `python3 -m unittest tests.test_handoff.HandoffSuffixTest -v`
Expected: 4 tests pass.

- [ ] **Step 5.2.a: Write the failing tests for primary-branch slug requirement**

Append to `HandoffSuffixTest`:

```python
    def test_primary_branch_requires_slug(self) -> None:
        # Helper: derive_suffix(current_branch, primary_branch, slug) -> str
        with self.assertRaises(self.handoff.HandoffError) as ctx:
            self.handoff.derive_suffix(current="main", primary="main", slug=None)
        self.assertIn("--slug", str(ctx.exception))

    def test_primary_branch_uses_slug_when_provided(self) -> None:
        self.assertEqual(
            self.handoff.derive_suffix(current="main", primary="main", slug="quick-fix"),
            "quick-fix",
        )

    def test_non_primary_branch_uses_branch_name(self) -> None:
        self.assertEqual(
            self.handoff.derive_suffix(current="user/feat", primary="main", slug=None),
            "user-feat",
        )

    def test_non_primary_branch_ignores_slug(self) -> None:
        self.assertEqual(
            self.handoff.derive_suffix(current="user/feat", primary="main", slug="ignored"),
            "user-feat",
        )
```

- [ ] **Step 5.2.b: Run to confirm failure**

Run: `python3 -m unittest tests.test_handoff.HandoffSuffixTest -v`
Expected: 4 of the original tests pass; the 4 new tests fail because `HandoffError` and `derive_suffix` are undefined.

- [ ] **Step 5.2.c: Implement `derive_suffix` and `HandoffError`**

Edit `handoff.py`. Add:

```python
class HandoffError(Exception):
    """Raised when the helper cannot proceed."""


def derive_suffix(*, current: str, primary: str, slug: str | None) -> str:
    if current != primary:
        return sanitize_suffix(current)
    if not slug:
        raise HandoffError(
            "current branch is the primary branch; pass --slug with a 2-4 word "
            "kebab-case summary so the output filename is meaningful."
        )
    return sanitize_suffix(slug)
```

- [ ] **Step 5.2.d: Run to confirm pass**

Run: `python3 -m unittest tests.test_handoff.HandoffSuffixTest -v`
Expected: 8 tests pass.

- [ ] **Step 5.3: Commit**

```bash
git add catalog/skills/handoff/scripts/handoff.py tests/test_handoff.py
git commit -m "feat(handoff): suffix derivation with branch sanitization and primary-branch slug"
```

---

### Task 6: handoff.py — template resolution and self-heal

Add the agent-plugins lookup chain (repo → home → bundled) and the home-scope self-heal.

**Files:**
- Modify: `catalog/skills/handoff/scripts/handoff.py`
- Modify: `tests/test_handoff.py`

- [ ] **Step 6.1.a: Write the failing tests for template resolution**

Append to `tests/test_handoff.py`:

```python
class HandoffTemplateResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.handoff = _load_handoff_module()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_repo_scope_wins_over_home_and_bundled(self) -> None:
        repo_root = self.tmp_path / "repo"
        repo_root.mkdir()
        repo_template = self._write(
            repo_root / ".agent-plugins" / "bento" / "bento" / "handoff" / "template.md",
            "REPO\n",
        )
        home_template = self._write(
            self.tmp_path / "home" / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md",
            "HOME\n",
        )
        bundled = self._write(self.tmp_path / "bundled.md", "BUNDLED\n")
        resolved = self.handoff.resolve_template(
            repo_root=repo_root,
            xdg_config_home=self.tmp_path / "home",
            bundled=bundled,
        )
        self.assertEqual(resolved, repo_template)

    def test_home_scope_wins_over_bundled_when_repo_absent(self) -> None:
        repo_root = self.tmp_path / "repo"
        repo_root.mkdir()
        home_template = self._write(
            self.tmp_path / "home" / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md",
            "HOME\n",
        )
        bundled = self._write(self.tmp_path / "bundled.md", "BUNDLED\n")
        resolved = self.handoff.resolve_template(
            repo_root=repo_root,
            xdg_config_home=self.tmp_path / "home",
            bundled=bundled,
        )
        self.assertEqual(resolved, home_template)

    def test_bundled_used_when_no_overrides(self) -> None:
        repo_root = self.tmp_path / "repo"
        repo_root.mkdir()
        bundled = self._write(self.tmp_path / "bundled.md", "BUNDLED\n")
        resolved = self.handoff.resolve_template(
            repo_root=repo_root,
            xdg_config_home=self.tmp_path / "home",
            bundled=bundled,
        )
        self.assertEqual(resolved, bundled)

    def test_xdg_default_used_when_xdg_config_home_unset(self) -> None:
        # When xdg_config_home is None, resolve_template should default to ~/.config under HOME.
        fake_home = self.tmp_path / "fake-home"
        home_template = self._write(
            fake_home / ".config" / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md",
            "HOME\n",
        )
        bundled = self._write(self.tmp_path / "bundled.md", "BUNDLED\n")
        resolved = self.handoff.resolve_template(
            repo_root=self.tmp_path / "repo-not-existing",
            xdg_config_home=None,
            bundled=bundled,
            home=fake_home,
        )
        self.assertEqual(resolved, home_template)
```

- [ ] **Step 6.1.b: Run to confirm failure**

Run: `python3 -m unittest tests.test_handoff.HandoffTemplateResolutionTest -v`
Expected: FAIL — `resolve_template` not defined.

- [ ] **Step 6.1.c: Implement `resolve_template`**

Edit `handoff.py`. Add:

```python
MARKETPLACE = "bento"
PLUGIN_NAME = "bento"
TEMPLATE_REL = Path("handoff") / "template.md"


def resolve_template(
    *,
    repo_root: Path | None,
    xdg_config_home: Path | None,
    bundled: Path,
    home: Path | None = None,
) -> Path:
    candidates: list[Path] = []
    if repo_root is not None:
        candidates.append(
            repo_root / ".agent-plugins" / MARKETPLACE / PLUGIN_NAME / TEMPLATE_REL
        )
    if xdg_config_home is not None:
        base = xdg_config_home
    else:
        base = (home or Path.home()) / ".config"
    candidates.append(base / "agent-plugins" / MARKETPLACE / PLUGIN_NAME / TEMPLATE_REL)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    if bundled.is_file():
        return bundled
    raise HandoffError(f"no template found at any candidate path: {candidates}")
```

- [ ] **Step 6.1.d: Run to confirm pass**

Run: `python3 -m unittest tests.test_handoff.HandoffTemplateResolutionTest -v`
Expected: 4 tests pass.

- [ ] **Step 6.2.a: Write the failing test for self-heal**

Append to `tests/test_handoff.py`:

```python
class HandoffSelfHealTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.handoff = _load_handoff_module()
        self.bundled = self.tmp_path / "bundled.md"
        self.bundled.write_text("BUNDLED\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_self_heal_creates_home_scope_when_missing(self) -> None:
        xdg = self.tmp_path / "xdg"
        target = xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        self.assertFalse(target.exists())
        created = self.handoff.self_heal_home_template(
            xdg_config_home=xdg, bundled=self.bundled
        )
        self.assertTrue(created)
        self.assertEqual(target.read_text(encoding="utf-8"), "BUNDLED\n")

    def test_self_heal_leaves_existing_home_scope_alone(self) -> None:
        xdg = self.tmp_path / "xdg"
        target = xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        target.parent.mkdir(parents=True)
        target.write_text("CUSTOM\n", encoding="utf-8")
        created = self.handoff.self_heal_home_template(
            xdg_config_home=xdg, bundled=self.bundled
        )
        self.assertFalse(created)
        self.assertEqual(target.read_text(encoding="utf-8"), "CUSTOM\n")

    def test_self_heal_silently_no_ops_when_bundled_missing(self) -> None:
        xdg = self.tmp_path / "xdg"
        missing_bundle = self.tmp_path / "does-not-exist.md"
        created = self.handoff.self_heal_home_template(
            xdg_config_home=xdg, bundled=missing_bundle
        )
        self.assertFalse(created)
```

- [ ] **Step 6.2.b: Run to confirm failure**

Run: `python3 -m unittest tests.test_handoff.HandoffSelfHealTest -v`
Expected: FAIL — `self_heal_home_template` not defined.

- [ ] **Step 6.2.c: Implement `self_heal_home_template`**

Edit `handoff.py`. Add:

```python
import shutil


def self_heal_home_template(
    *, xdg_config_home: Path | None, bundled: Path, home: Path | None = None
) -> bool:
    if xdg_config_home is not None:
        base = xdg_config_home
    else:
        base = (home or Path.home()) / ".config"
    target = base / "agent-plugins" / MARKETPLACE / PLUGIN_NAME / TEMPLATE_REL
    if target.is_file():
        return False
    if not bundled.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundled, target)
    return True
```

- [ ] **Step 6.2.d: Run to confirm pass**

Run: `python3 -m unittest tests.test_handoff.HandoffSelfHealTest -v`
Expected: 3 tests pass.

- [ ] **Step 6.3: Commit**

```bash
git add catalog/skills/handoff/scripts/handoff.py tests/test_handoff.py
git commit -m "feat(handoff): template resolution and home-scope self-heal"
```

---

### Task 7: handoff.py — output path generation

Add the timestamped path generator.

**Files:**
- Modify: `catalog/skills/handoff/scripts/handoff.py`
- Modify: `tests/test_handoff.py`

- [ ] **Step 7.1.a: Write the failing tests**

Append to `tests/test_handoff.py`:

```python
from datetime import datetime


class HandoffPathGenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.handoff = _load_handoff_module()

    def test_path_format(self) -> None:
        moment = datetime(2026, 4, 25, 9, 5, 7)
        path = self.handoff.output_path(suffix="feat-foo", now=moment, tmp_root=Path("/tmp"))
        self.assertEqual(path, Path("/tmp/handoff-feat-foo-20260425-090507.md"))

    def test_two_consecutive_calls_with_different_seconds_yield_different_paths(self) -> None:
        a = self.handoff.output_path(
            suffix="x", now=datetime(2026, 4, 25, 9, 5, 7), tmp_root=Path("/tmp")
        )
        b = self.handoff.output_path(
            suffix="x", now=datetime(2026, 4, 25, 9, 5, 8), tmp_root=Path("/tmp")
        )
        self.assertNotEqual(a, b)
```

- [ ] **Step 7.1.b: Run to confirm failure**

Run: `python3 -m unittest tests.test_handoff.HandoffPathGenerationTest -v`
Expected: FAIL — `output_path` not defined.

- [ ] **Step 7.1.c: Implement `output_path`**

Edit `handoff.py`. Add at top of imports:

```python
from datetime import datetime
```

Add helper:

```python
def output_path(*, suffix: str, now: datetime, tmp_root: Path) -> Path:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    return tmp_root / f"handoff-{suffix}-{stamp}.md"
```

- [ ] **Step 7.1.d: Run to confirm pass**

Run: `python3 -m unittest tests.test_handoff.HandoffPathGenerationTest -v`
Expected: 2 tests pass.

- [ ] **Step 7.2: Commit**

```bash
git add catalog/skills/handoff/scripts/handoff.py tests/test_handoff.py
git commit -m "feat(handoff): timestamped output path generator"
```

---

### Task 8: handoff.py — wire main() to write the file

Wire all pieces together. The `main()` function:

1. Validates preconditions (already done in Task 4).
2. Reads input content from `--input <path>` or `--input -` (stdin).
3. Detects current branch and primary branch (uses `git_state` helpers).
4. Derives the suffix.
5. Resolves the template (only used so the agent can verify a specific override is in effect; the helper does NOT substitute into it — content comes from `--input`).
6. Self-heals the home-scope template.
7. Generates the output path.
8. Writes the input content to the path.
9. Prints the path to stdout.

**Files:**
- Modify: `catalog/skills/handoff/scripts/handoff.py`
- Modify: `tests/test_handoff.py`

- [ ] **Step 8.1.a: Write the integration test for happy-path file write**

Append to `tests/test_handoff.py`:

```python
class HandoffEndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.repo = self.tmp_path / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feat/foo"], cwd=self.repo, check=True
        )
        self.input_path = self.tmp_path / "body.md"
        self.input_path.write_text("filled handoff\n", encoding="utf-8")
        self.tmp_root = self.tmp_path / "tmp"
        self.tmp_root.mkdir()
        self.xdg = self.tmp_path / "xdg"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_writes_file_under_tmp_root_with_branch_suffix(self) -> None:
        env = os.environ.copy()
        env["HANDOFF_TMP_ROOT"] = str(self.tmp_root)
        env["XDG_CONFIG_HOME"] = str(self.xdg)
        env["BENTO_EXPEDITION_SCRIPT"] = str(self.tmp_path / "no-such-expedition.py")
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Stdout is the absolute path of the file that was written.
        path_line = result.stdout.strip()
        self.assertTrue(path_line.startswith(str(self.tmp_root)))
        self.assertIn("feat-foo-", path_line)
        self.assertTrue(path_line.endswith(".md"))
        self.assertEqual(
            Path(path_line).read_text(encoding="utf-8"), "filled handoff\n"
        )

    def test_stdin_input_path(self) -> None:
        env = os.environ.copy()
        env["HANDOFF_TMP_ROOT"] = str(self.tmp_root)
        env["XDG_CONFIG_HOME"] = str(self.xdg)
        env["BENTO_EXPEDITION_SCRIPT"] = str(self.tmp_path / "no-such-expedition.py")
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", "-"],
            cwd=self.repo,
            input="from stdin\n",
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        written = Path(result.stdout.strip())
        self.assertEqual(written.read_text(encoding="utf-8"), "from stdin\n")

    def test_self_heal_creates_home_scope_template_during_run(self) -> None:
        env = os.environ.copy()
        env["HANDOFF_TMP_ROOT"] = str(self.tmp_root)
        env["XDG_CONFIG_HOME"] = str(self.xdg)
        env["BENTO_EXPEDITION_SCRIPT"] = str(self.tmp_path / "no-such-expedition.py")
        target = self.xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        self.assertFalse(target.exists())
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(target.exists())
        self.assertIn("## Next action", target.read_text(encoding="utf-8"))

    def test_primary_branch_without_slug_fails(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "main"], cwd=self.repo, check=True
        )
        env = os.environ.copy()
        env["HANDOFF_TMP_ROOT"] = str(self.tmp_root)
        env["XDG_CONFIG_HOME"] = str(self.xdg)
        env["BENTO_EXPEDITION_SCRIPT"] = str(self.tmp_path / "no-such-expedition.py")
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--slug", result.stderr)

    def test_primary_branch_with_slug_uses_slug_in_filename(self) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "main"], cwd=self.repo, check=True
        )
        env = os.environ.copy()
        env["HANDOFF_TMP_ROOT"] = str(self.tmp_root)
        env["XDG_CONFIG_HOME"] = str(self.xdg)
        env["BENTO_EXPEDITION_SCRIPT"] = str(self.tmp_path / "no-such-expedition.py")
        result = subprocess.run(
            [str(HANDOFF_SCRIPT), "--input", str(self.input_path), "--slug", "quick-hop"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("quick-hop-", result.stdout)
```

- [ ] **Step 8.1.b: Run to confirm failure**

Run: `python3 -m unittest tests.test_handoff.HandoffEndToEndTest -v`
Expected: FAIL across the new tests.

- [ ] **Step 8.1.c: Wire `main()`**

Edit `catalog/skills/handoff/scripts/handoff.py`. Add at the top of the imports block:

```python
from datetime import datetime
```

Add a sibling-script importable for `git_state` near the top, after argparse imports:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
import git_state  # noqa: E402
```

Add helpers used by `main`:

```python
def _read_input(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    return Path(arg).read_text(encoding="utf-8")


def _bundled_template_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "references"
        / "templates"
        / "handoff.md"
    )


def _xdg_config_home() -> Path | None:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if not raw:
        return None
    return Path(raw)


def _tmp_root() -> Path:
    raw = os.environ.get("HANDOFF_TMP_ROOT")
    if raw:
        return Path(raw)
    return Path("/tmp")
```

Replace `main()` end-to-end with:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cwd = Path.cwd().resolve()
    if not _is_inside_work_tree(cwd):
        print(
            "/handoff: not in a git repository; refusing to write a handoff file.",
            file=sys.stderr,
        )
        return 2
    if not _has_named_branch(cwd):
        print(
            "/handoff: HEAD is detached; refusing to write a handoff file. "
            "Check out a named branch.",
            file=sys.stderr,
        )
        return 2
    expedition_name = _active_expedition(cwd)
    if expedition_name:
        print(
            f"/handoff: active expedition {expedition_name} detected; "
            f"use the expedition skill's session-end protocol instead "
            f"(update docs/expeditions/{expedition_name}/handoff.md via "
            f"expedition/scripts/expedition.py).",
            file=sys.stderr,
        )
        return 2

    checkout_root = git_state.detect_checkout_root(cwd)
    primary_branch, _warnings = git_state.detect_primary_branch(checkout_root)
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    try:
        suffix = derive_suffix(
            current=current_branch, primary=primary_branch, slug=args.slug
        )
    except HandoffError as exc:
        print(f"/handoff: {exc}", file=sys.stderr)
        return 2

    bundled = _bundled_template_path()
    xdg = _xdg_config_home()
    self_heal_home_template(xdg_config_home=xdg, bundled=bundled)

    # Resolve template just to validate the lookup chain works; we do not
    # interpolate into it. The caller has already produced filled-in content.
    try:
        resolve_template(repo_root=checkout_root, xdg_config_home=xdg, bundled=bundled)
    except HandoffError as exc:
        print(f"/handoff: {exc}", file=sys.stderr)
        return 2

    body = _read_input(args.input)
    target = output_path(suffix=suffix, now=datetime.now(), tmp_root=_tmp_root())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")

    if args.verbose:
        print(f"/handoff: wrote {target}", file=sys.stderr)
    print(str(target))
    return 0
```

- [ ] **Step 8.1.d: Run end-to-end tests**

Run: `python3 -m unittest tests.test_handoff -v`
Expected: all `tests.test_handoff` tests pass.

- [ ] **Step 8.2: Commit**

```bash
git add catalog/skills/handoff/scripts/handoff.py tests/test_handoff.py
git commit -m "feat(handoff): wire main() to derive suffix, resolve template, write file"
```

---

### Task 9: SKILL.md

Skill prose for the agent. Keep it terse.

**Files:**
- Create: `catalog/skills/handoff/SKILL.md`

- [ ] **Step 9.1: Write SKILL.md**

Create `catalog/skills/handoff/SKILL.md` with this content:

```markdown
---
name: handoff
description: Use when the current session needs a structured reboot prompt — context-window pressure, delegation to a teammate, or any user-initiated session handoff. Writes a markdown file under /tmp/ with seven labeled slots and echoes the contents back to chat.
recommended_model: high
---

# Handoff

## Model Guidance

Recommended model: high.

This skill's load-bearing task is distilling in-flight conversation state into a
crisp next-action paragraph. That distillation benefits from a higher-capability
model. Lower-capability models will produce vague summaries that defeat the
purpose of the prompt.

## When to use

- Context-window pressure: the current session is approaching compaction.
- Delegation: the user is handing remaining work to a different session, role,
  or person.
- General user-initiated handoff: the user invoked `/handoff` directly.

## When NOT to use

- A long-idle resumption ("pick up next week"). `/handoff` is not designed for
  state that must survive long gaps.
- Subagent dispatch. The skill writes a file the user will read or copy; it
  does not feed the prompt to the Agent tool.
- Inside an active expedition. Defer to the expedition skill's session-end
  protocol (update `docs/expeditions/<name>/handoff.md` via
  `expedition/scripts/expedition.py`).

## Preconditions and short-circuit behavior

The skill operates only when all three preconditions hold:

1. The current working directory is inside a git repository.
2. HEAD resolves to a named branch (not detached).
3. No active expedition is detected in the current worktree.

When any precondition fails, the helper exits non-zero with a one-line
diagnostic and writes nothing.

## Template structure

The agent fills body content under each of these seven labeled headings, in
order:

1. **Next action** — the single concrete next step for the new session.
2. **Original task** — the user's original request, in one line.
3. **Branch & worktree** — current branch, worktree path, primary branch.
4. **Verification state** — what was run, what passed, what failed, what was
   not yet tested.
5. **Decisions & dead-ends** — non-obvious choices, approaches ruled out and
   why.
6. **Pending decisions / blockers** — questions waiting on the user, external
   blockers.
7. **Notes** — free-form prose for in-flight reasoning that does not fit a
   slot.

The on-disk template is editable. A user override (repo-scope or home-scope)
may add, remove, rename, or reorder headings; the agent's runtime job is to
write content under whatever headings the resolved template provides.

## Customization

The template is resolved through the `agent-plugins` convention:

1. `<repo-root>/.agent-plugins/bento/bento/handoff/template.md`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/handoff/template.md`
   (default `~/.config/agent-plugins/bento/bento/handoff/template.md` when
   `XDG_CONFIG_HOME` is unset)
3. The plugin-bundled default at `handoff/references/templates/handoff.md`.

First match wins. Lookup is per-file. Users override only the file they want
to override; missing files fall through.

## Workflow

1. Read the user's stated reason for handoff (if any) and review the
   conversation state.
2. Compose body text under each heading from the resolved template. Be
   concrete; the next agent will not see this conversation.
3. Run the helper:

```bash
handoff/scripts/handoff.py --input <path-to-filled-template>
```

   On the primary branch, also pass `--slug <kebab-case-summary>` (2–4 words).
   Use `--input -` to pipe content via stdin instead of writing to a temp file.

4. The helper prints the absolute path of the file it wrote to stdout.
5. Echo the full contents of the file back to chat in the same response so the
   user can see what was captured without opening the file.

Invoke the helper by script path (`handoff/scripts/handoff.py ...`) so
approvals stay scoped to the script.

## Output filename

```
/tmp/handoff-<suffix>-<YYYYMMDD-HHMMSS>.md
```

`<suffix>` is the current branch name with `/` and other non-`[A-Za-z0-9._-]`
characters replaced with `-`. On the primary branch (where there is no useful
branch suffix), `<suffix>` is the agent-supplied `--slug`.

## Non-Negotiable Rules

- Do not write a file when preconditions fail.
- Do not invent a branch name when HEAD is detached.
- Do not duplicate or replace the expedition skill's `handoff.md` when an
  expedition is active.
- Do not perform `{{token}}` substitution on the template; write prose under
  each heading.
- Do not modify a repo-scope or home-scope user-edited template; treat both as
  read-only.
- Do not chat-only the output. Always write the file when preconditions pass.
- Always echo the file contents in chat after writing.

## Stop conditions

Stop and ask the user if:

- The conversation contains no clear next action and you cannot infer one with
  reasonable confidence.
- An expedition is active. Defer to the expedition skill's session-end flow.
- Multiple unrelated threads are in flight and a single handoff would
  misrepresent the state. Suggest the user pick the thread to capture.
```

- [ ] **Step 9.2: Verify length and structure**

Run: `wc -l catalog/skills/handoff/SKILL.md`
Expected: under 250 lines.

Run: `grep -c '^## ' catalog/skills/handoff/SKILL.md`
Expected: 9 (Model Guidance, When to use, When NOT to use, Preconditions, Template structure, Customization, Workflow, Output filename, Non-Negotiable Rules, Stop conditions — note: 10 actually if we count, accept either; the assertion is just "≥ 8 sections").

(Adjust the assertion to `[ "$(grep -c '^## ' catalog/skills/handoff/SKILL.md)" -ge 8 ]` if the helper run is being scripted.)

- [ ] **Step 9.3: Commit**

```bash
git add catalog/skills/handoff/SKILL.md
git commit -m "feat(handoff): add SKILL.md prose"
```

---

### Task 10: SessionStart hook script

Add `seed-agent-plugins.py` to the bento Claude plugin's hooks. The script copies the bundled template into the home-scope agent-plugins path on first session start. Idempotent. Permission failures are non-fatal.

**Files:**
- Create: `catalog/hooks/bento/scripts/seed-agent-plugins.py`
- Create: `tests/test_seed_agent_plugins.py`

- [ ] **Step 10.1.a: Write the failing test**

Create `tests/test_seed_agent_plugins.py`:

```python
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = (
    REPO_ROOT
    / "catalog"
    / "hooks"
    / "bento"
    / "scripts"
    / "seed-agent-plugins.py"
)


class SeedAgentPluginsHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_fake_plugin_root(self) -> Path:
        """Layout mirroring the installed Claude plugin under the test temp dir."""
        plugin_root = self.tmp_path / "plugin"
        bundled = (
            plugin_root
            / "skills"
            / "handoff"
            / "references"
            / "templates"
            / "handoff.md"
        )
        bundled.parent.mkdir(parents=True)
        bundled.write_text("BUNDLED\n", encoding="utf-8")
        return plugin_root

    def _run(self, plugin_root: Path, *, xdg: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(xdg)
        return subprocess.run(
            [str(HOOK_SCRIPT), str(plugin_root)],
            input=json.dumps({"session_id": "abc"}),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_first_run_creates_home_scope_template(self) -> None:
        plugin_root = self._make_fake_plugin_root()
        xdg = self.tmp_path / "xdg"
        target = xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        self.assertFalse(target.exists())
        result = self._run(plugin_root, xdg=xdg)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "BUNDLED\n")

    def test_second_run_does_not_overwrite(self) -> None:
        plugin_root = self._make_fake_plugin_root()
        xdg = self.tmp_path / "xdg"
        target = xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        target.parent.mkdir(parents=True)
        target.write_text("USER EDITED\n", encoding="utf-8")
        before = target.stat().st_mtime_ns
        result = self._run(plugin_root, xdg=xdg)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "USER EDITED\n")
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_missing_bundled_default_no_ops_silently(self) -> None:
        plugin_root = self.tmp_path / "empty-plugin"
        plugin_root.mkdir()
        xdg = self.tmp_path / "xdg"
        result = self._run(plugin_root, xdg=xdg)
        # Hook must not block session start under any circumstance.
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        target = (
            xdg / "agent-plugins" / "bento" / "bento" / "handoff" / "template.md"
        )
        self.assertFalse(target.exists())

    def test_unwritable_xdg_no_ops_silently(self) -> None:
        plugin_root = self._make_fake_plugin_root()
        xdg = self.tmp_path / "xdg"
        xdg.mkdir()
        os.chmod(xdg, 0o500)  # read+execute only
        try:
            result = self._run(plugin_root, xdg=xdg)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
        finally:
            os.chmod(xdg, 0o700)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 10.1.b: Run to confirm failure**

Run: `python3 -m unittest tests.test_seed_agent_plugins -v`
Expected: FAIL — script does not exist.

- [ ] **Step 10.1.c: Write the hook script**

Create `catalog/hooks/bento/scripts/seed-agent-plugins.py` with:

```python
#!/usr/bin/env python3
"""SessionStart hook: copies bento's bundled handoff template into the
home-scope agent-plugins path if it is missing. Idempotent and non-fatal."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".config"


def seed_handoff_template(plugin_root: Path) -> None:
    bundled = (
        plugin_root
        / "skills"
        / "handoff"
        / "references"
        / "templates"
        / "handoff.md"
    )
    if not bundled.is_file():
        return
    target = (
        _xdg_config_home()
        / "agent-plugins"
        / "bento"
        / "bento"
        / "handoff"
        / "template.md"
    )
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundled, target)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # Drain stdin so the harness does not see SIGPIPE; payload is unused.
    try:
        sys.stdin.read()
    except Exception:
        pass
    if len(argv) < 2:
        return 0
    plugin_root = Path(argv[1])
    try:
        seed_handoff_template(plugin_root)
    except Exception:
        # Never block session start. Permission errors, missing dirs, etc.
        # are all swallowed.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Mark it executable:

```bash
chmod +x catalog/hooks/bento/scripts/seed-agent-plugins.py
```

- [ ] **Step 10.1.d: Run to confirm pass**

Run: `python3 -m unittest tests.test_seed_agent_plugins -v`
Expected: 4 tests pass.

- [ ] **Step 10.2: Commit**

```bash
git add catalog/hooks/bento/scripts/seed-agent-plugins.py tests/test_seed_agent_plugins.py
git commit -m "feat(bento-hook): add SessionStart hook to seed agent-plugins handoff template"
```

---

### Task 11: Wire SessionStart hook into hooks.json

Add a `SessionStart` array to the bento plugin's `catalog/hooks/bento/hooks.json` so the new script runs.

**Files:**
- Modify: `catalog/hooks/bento/hooks.json`

- [ ] **Step 11.1: Update hooks.json**

Replace the contents of `catalog/hooks/bento/hooks.json` with:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/auto-allow.py bento ${CLAUDE_PLUGIN_ROOT}"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/seed-agent-plugins.py ${CLAUDE_PLUGIN_ROOT}"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 11.2: Verify with build-plugins copy**

The build script's `copy_hooks` does `shutil.copytree` of `catalog/hooks/bento/` into `plugins/claude/bento/hooks/`. Verify the new file is picked up:

```bash
BENTO_SKIP_VERIFY=1 BENTO_SKIP_CLAUDE_VALIDATE=1 scripts/build-plugins
```

Then check:

```bash
test -f plugins/claude/bento/hooks/scripts/seed-agent-plugins.py
grep -q SessionStart plugins/claude/bento/hooks/hooks.json
```

Both should succeed (exit 0).

- [ ] **Step 11.3: Commit**

```bash
git add catalog/hooks/bento/hooks.json
git commit -m "feat(bento-hook): register SessionStart seed hook"
```

(The `plugins/claude/bento/...` regenerated artifacts from build-plugins are committed in Task 14 alongside the version bump.)

---

### Task 12: Codex installer seeding step

Add a function to `_codex-installer-lib.sh` that copies the bundled template into the agent-plugins path.

**Files:**
- Modify: `install/_codex-installer-lib.sh`
- Modify: `tests/test_codex_installer.py`

- [ ] **Step 12.1.a: Write the failing test**

Append to `tests/test_codex_installer.py` (inside `CodexInstallerTest`):

```python
    def test_home_install_seeds_agent_plugins_handoff_template(self) -> None:
        install_root = self.root / "home-seed"
        plugin_root, _marketplace_path, _codex_cache_root, _codex_config_path, _result = self.run_installer(
            "home",
            install_root,
            enable_codex=True,
        )
        # The fixture's bento plugin includes a handoff skill bundled template.
        seeded = (
            install_root
            / ".config"
            / "agent-plugins"
            / "bento"
            / "bento"
            / "handoff"
            / "template.md"
        )
        self.assertTrue(seeded.exists(), msg=f"expected seeded template at {seeded}")
        self.assertEqual(seeded.read_text(encoding="utf-8"), "BUNDLED\n")

    def test_project_install_seeds_agent_plugins_handoff_template(self) -> None:
        install_root = self.root / "project-seed"
        _plugin_root, _marketplace_path, _codex_cache_root, _codex_config_path, _result = self.run_installer(
            "project",
            install_root,
        )
        seeded = (
            install_root
            / ".agent-plugins"
            / "bento"
            / "bento"
            / "handoff"
            / "template.md"
        )
        self.assertTrue(seeded.exists(), msg=f"expected seeded template at {seeded}")

    def test_seed_does_not_overwrite_existing_home_scope_template(self) -> None:
        install_root = self.root / "home-noop"
        seeded = (
            install_root
            / ".config"
            / "agent-plugins"
            / "bento"
            / "bento"
            / "handoff"
            / "template.md"
        )
        seeded.parent.mkdir(parents=True)
        seeded.write_text("USER EDITED\n", encoding="utf-8")
        self.run_installer("home", install_root, enable_codex=True)
        self.assertEqual(seeded.read_text(encoding="utf-8"), "USER EDITED\n")
```

The test fixture bento archive must include the handoff skill. Update `_write_main_archive` in the same file. Find the existing block:

```python
        for name, category in plugin_defs.items():
            plugin_dir = source_root / "plugins" / "codex" / name
            (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
            (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"interface": {"category": category}}, indent=2) + "\n",
                encoding="utf-8",
            )
            (plugin_dir / "README.txt").write_text(f"{name}\n", encoding="utf-8")
```

Replace with:

```python
        for name, category in plugin_defs.items():
            plugin_dir = source_root / "plugins" / "codex" / name
            (plugin_dir / ".codex-plugin").mkdir(parents=True, exist_ok=True)
            (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"interface": {"category": category}}, indent=2) + "\n",
                encoding="utf-8",
            )
            (plugin_dir / "README.txt").write_text(f"{name}\n", encoding="utf-8")
            if name == "bento":
                handoff_template = (
                    plugin_dir
                    / "skills"
                    / "handoff"
                    / "references"
                    / "templates"
                    / "handoff.md"
                )
                handoff_template.parent.mkdir(parents=True, exist_ok=True)
                handoff_template.write_text("BUNDLED\n", encoding="utf-8")
```

Also adjust the `home_install_writes_paths_relative_to_marketplace_file_and_enables_bento` test (around line 56) — it may have `(plugin_root / "bento" / "README.txt")` that still passes; no change needed for that assertion. Leave it alone.

Update `setUp` if `run_installer` does not pass through XDG. Looking at the existing helper, it sets `BENTO_INSTALL_ROOT` to a per-test path under `self.root`. Home-scope installs need the install lib to use `${install_root}/.config` as the XDG default. The lib already calls `${HOME}` indirectly — but the existing test uses `install_root` as `${HOME}` via the `codex-home.sh` wrapper. Since these tests run `_codex-installer-lib.sh` directly (not via codex-home.sh), the seed function must compute the home-scope base from `${BENTO_INSTALL_ROOT}/.config` when scope is `home`, NOT from `$HOME`. The implementation in step 12.1.b reflects this (it uses `BENTO_INSTALL_ROOT` for home scope, mirroring how `codex-home.sh` derives all home paths under `$HOME`).

The path the test asserts for home — `install_root / ".config" / "agent-plugins" / ...` — therefore matches what the install lib will write when given `BENTO_INSTALL_SCOPE=home BENTO_INSTALL_ROOT=<install_root>`.

- [ ] **Step 12.1.b: Run to confirm failure**

Run: `python3 -m unittest tests.test_codex_installer -v`
Expected: 3 new tests fail.

- [ ] **Step 12.1.c: Add the seeding function to the installer lib**

Edit `install/_codex-installer-lib.sh`. After the closing `done` of the existing `for plugin in "${PLUGIN_NAMES[@]}"` loop (and before the external-plugins loop), add:

```bash
seed_agent_plugins_handoff() {
  local source_template="${PLUGIN_ROOT}/bento/skills/handoff/references/templates/handoff.md"
  if [[ ! -f "$source_template" ]]; then
    return 0
  fi
  local agent_plugins_root
  case "$INSTALL_SCOPE" in
    home)
      agent_plugins_root="${XDG_CONFIG_HOME:-$INSTALL_ROOT/.config}/agent-plugins"
      ;;
    project)
      agent_plugins_root="${INSTALL_ROOT}/.agent-plugins"
      ;;
    *)
      return 0
      ;;
  esac
  local target_dir="${agent_plugins_root}/bento/bento/handoff"
  local target_file="${target_dir}/template.md"
  if [[ -f "$target_file" ]]; then
    log "agent-plugins handoff template already present at ${target_file}"
    return 0
  fi
  mkdir -p "$target_dir"
  cp "$source_template" "$target_file"
  log "seeded agent-plugins handoff template at ${target_file}"
}

seed_agent_plugins_handoff
```

Note: when `BENTO_INSTALL_SCOPE=home` and the installer is invoked via `codex-home.sh`, `$INSTALL_ROOT` equals `$HOME`. The `$INSTALL_ROOT/.config` fallback therefore matches XDG's default of `$HOME/.config` exactly. When `XDG_CONFIG_HOME` is set in the user's env, it wins as the spec requires.

- [ ] **Step 12.1.d: Run to confirm pass**

Run: `python3 -m unittest tests.test_codex_installer -v`
Expected: all tests pass, including the 3 new ones.

- [ ] **Step 12.2: Commit**

```bash
git add install/_codex-installer-lib.sh tests/test_codex_installer.py
git commit -m "feat(install): seed agent-plugins handoff template during Codex install"
```

---

### Task 13: Register handoff under bento in build-plugins

Add `"handoff"` to `PLUGIN_DEFS["bento"]["skills"]` in `scripts/build-plugins`. This makes the build copy `catalog/skills/handoff/` into `plugins/claude/bento/skills/handoff/` and `plugins/codex/bento/skills/handoff/`.

**Files:**
- Modify: `scripts/build-plugins`

- [ ] **Step 13.1: Add the skill to the bento plugin definition**

Edit `scripts/build-plugins`. Find the block:

```python
        "skills": [
            "closure",
            "launch-work",
            "land-work",
            "swarm",
            "expedition",
            "build-vs-buy",
            "generate-audit",
            "project-memory",
            "compress-docs",
            "beads-issue-flow",
            "github-issue-flow",
            "go-pgx-goose",
            "react-vite-mantine",
            "graphql-gqlgen-gql-tada",
        ],
```

Insert `"handoff",` so the list becomes (place it next to similar workflow skills):

```python
        "skills": [
            "closure",
            "launch-work",
            "land-work",
            "handoff",
            "swarm",
            "expedition",
            "build-vs-buy",
            "generate-audit",
            "project-memory",
            "compress-docs",
            "beads-issue-flow",
            "github-issue-flow",
            "go-pgx-goose",
            "react-vite-mantine",
            "graphql-gqlgen-gql-tada",
        ],
```

- [ ] **Step 13.2: Verify the skill is registered**

Run: `python3 -c "import importlib.machinery, importlib.util; loader = importlib.machinery.SourceFileLoader('bp', 'scripts/build-plugins'); spec = importlib.util.spec_from_loader('bp', loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m); print('handoff' in m.PLUGIN_DEFS['bento']['skills'])"`
Expected: `True`

- [ ] **Step 13.3: Commit**

```bash
git add scripts/build-plugins
git commit -m "feat(build): register handoff skill under bento plugin"
```

---

### Task 14: Bump versions and rebuild plugins

Run the version bumper, then rebuild generated artifacts. Both go in the same commit.

**Files:**
- Modify: `catalog/plugin-versions.json` (via `scripts/bump-plugin-versions`)
- Regenerate: `plugins/claude/bento/...`, `plugins/codex/bento/...`, `.claude-plugin/marketplace.json`, `.agents/plugins/marketplace.json`

- [ ] **Step 14.1: Run the version bumper**

Run: `scripts/bump-plugin-versions`
Expected stdout (JSON-shaped): `bumps` includes `bento` with `from`/`to` differing by patch (e.g. `1.0.28` → `1.0.29`).

If the bumps map does NOT include bento, that means the version bumper does not consider the new `catalog/skills/handoff/` files relevant. Verify which paths it sees with `git diff --name-only $(git log -1 --format=%H -- catalog/plugin-versions.json)`. If `catalog/skills/handoff/SKILL.md` shows up but bento is not in the affected set, that is a bug in `affected_plugins()` — see "Spec limitations" at the end of this plan. In that case, hand-bump by editing `catalog/plugin-versions.json` (set `bento` patch +1) and proceed; flag the bug for follow-up.

- [ ] **Step 14.2: Rebuild plugins**

Run: `scripts/build-plugins`
Expected: build runs to completion. The unittest discover step at the end runs all tests including `test_handoff` and `test_seed_agent_plugins`, and they all pass. The `claude plugin validate` step also passes (or is skipped if `BENTO_SKIP_CLAUDE_VALIDATE=1` is in the environment).

If `claude` is not on PATH, run: `BENTO_SKIP_CLAUDE_VALIDATE=1 scripts/build-plugins` and note that the skipped validation must be confirmed manually before merge.

- [ ] **Step 14.3: Inspect generated outputs**

Run: `ls plugins/claude/bento/skills/handoff/ plugins/codex/bento/skills/handoff/`
Expected: each contains `SKILL.md`, `scripts/handoff.py`, `scripts/git_state.py`, and `references/templates/handoff.md`.

Run: `test -f plugins/claude/bento/hooks/scripts/seed-agent-plugins.py && echo OK`
Expected: `OK`

Run: `grep -A2 SessionStart plugins/claude/bento/hooks/hooks.json`
Expected: prints the SessionStart block.

- [ ] **Step 14.4: Stage and commit**

```bash
git add catalog/plugin-versions.json plugins/ .claude-plugin/marketplace.json .agents/plugins/marketplace.json
git commit -m "chore(plugins): rebuild bento for handoff skill"
```

---

### Task 15: End-to-end smoke test in this worktree

Verify the full skill works on a real branch. This is a manual run; no test code is added.

**Files:**
- No file edits.

- [ ] **Step 15.1: Run the helper directly**

From the worktree root, run:

```bash
echo "test body" | catalog/skills/handoff/scripts/handoff.py --input -
```

Expected: prints a path of the form `/tmp/handoff-spec-agent-plugins-convention-<timestamp>.md`. Contents of that file equal `test body\n`.

Run:

```bash
cat $(echo "test body" | catalog/skills/handoff/scripts/handoff.py --input -)
```

Expected: prints `test body`.

- [ ] **Step 15.2: Verify home-scope template was self-healed**

Run: `ls -la "${XDG_CONFIG_HOME:-$HOME/.config}/agent-plugins/bento/bento/handoff/template.md"`
Expected: file exists. (If it already existed before this run, its mtime was preserved — confirm via the test suite's `test_self_heal_leaves_existing_home_scope_alone` for the unit-level guarantee.)

- [ ] **Step 15.3: Verify expedition refusal still works**

If you happen to have an active expedition in another worktree, run the helper there and confirm it refuses with the expedition-active diagnostic. If no expedition is active anywhere, skip this step and note it in the final summary.

- [ ] **Step 15.4: No commit needed**

Smoke test only.

---

### Task 16: Final verification gates

Run the full test suite and the build script once more end-to-end before declaring the work landable.

**Files:**
- No file edits.

- [ ] **Step 16.1: Full test suite**

Run: `python3 -m unittest discover -s tests -t .`
Expected: all tests pass.

- [ ] **Step 16.2: Full build**

Run: `scripts/build-plugins`
Expected: succeeds. If `claude plugin validate` is unavailable, run with `BENTO_SKIP_CLAUDE_VALIDATE=1` and note this in the final summary.

- [ ] **Step 16.3: Working tree clean**

Run: `git status`
Expected: clean. The build should not produce any further uncommitted changes (Task 14 already committed the regenerated artifacts).

- [ ] **Step 16.4: No commit needed**

Verification only.

---

## Spec limitations and follow-ups discovered during planning

These are notes for the human reviewer. The spec at `docs/specs/2026-04-24-handoff-skill-design.md` is marked Approved but is treated as a work in progress per the user's directive.

1. **`scripts/bump-plugin-versions` does not currently recognize hook changes.** Looking at `affected_plugins()` in `scripts/bump-plugin-versions:75-100`: it considers paths under `catalog/skills/<skill>/` (mapped to plugins via the `skills` lists in `PLUGIN_DEFS`) and a handful of "global" files (`scripts/build-plugins`). It does not consider `catalog/hooks/<hook>/` paths. Because this plan adds a new skill *and* a new hook script, the skill addition triggers a bento bump and the hook ride along happily; however, a future change that touched only the bento hook script would not trigger any bump. Worth a follow-up to extend `affected_plugins()` to map `catalog/hooks/<hook>/` paths to plugins via the `hooks: <hook>` field in `PLUGIN_DEFS`. Out of scope for this plan.

2. **Spec says "the helper does not perform `{{token}}` substitution" but also instructs `handoff.py` to "Resolve the template via the agent-plugins lookup chain."** The plan implements both: the template is resolved (so the agent and the helper agree on which file would be used if interpolation existed), but the bytes written to disk are entirely `--input`-supplied. The resolved template path is not currently surfaced to the agent; if the user wants the agent to print "using template at <path>" alongside the file contents, that's a small extension to `main()` to emit the resolved template path to stderr (or stdout) too. Spec is silent — flagging.

3. **Spec says "There is no chat-only mode. There is no pre-write approval step."** The runtime contract therefore depends on the agent reading the file back and echoing it. SKILL.md instructs the agent to do this, but the helper itself cannot enforce it. A future refinement could have the helper print the file body to stdout *after* a final blank line and the path, so the agent never has to re-read the file. Spec is silent — flagging.

4. **Spec says expedition discover is "the authoritative source of truth" but does not specify the helper's behavior when `expedition.py` is missing.** This plan treats a missing expedition script as "no active expedition" (and falls through). That is the safest interpretation given that handoff and expedition ship in the same plugin and the absence of expedition.py would only happen in a partially-installed or broken environment. If the desired behavior is instead to *fail*, that is a one-line change in `_active_expedition`. Spec is silent — flagging.

5. **Repo-root signal from agent runtime.** The convention spec says plugins SHOULD use the agent runtime's project-root signal when one is exposed. Claude Code does not currently expose a stable env var for the project root accessible to plugin scripts (`CLAUDE_PROJECT_DIR` exists in some flows but is not contractual). This plan uses `git rev-parse --show-toplevel` from the helper's cwd, which matches the convention spec's documented fallback. Worth confirming with the user that this fallback is acceptable for now.

6. **`catalog/skills/handoff/scripts/git_state.py` is a verbatim copy.** The launch-work and expedition skills each maintain their own copies of this file, so this plan follows the same pattern. A follow-up could extract a shared helper into a non-skill location and have the build script copy it into each skill's `scripts/` directory at build time, but that is an orthogonal cleanup.

7. **Smoke-test run in Task 15 is in this worktree (not primary).** Because the suffix is sanitized branch name and this branch is `spec-agent-plugins-convention`, the file lands at `/tmp/handoff-spec-agent-plugins-convention-<stamp>.md`. Long, but valid. If the user later wants a configurable max length, that is a future refinement; the spec is silent.

8. **`SessionStart` hook only seeds bento/handoff today.** The spec calls this out as intentional v1 scoping. A future bento skill that needs an agent-plugins file would either (a) extend `seed-agent-plugins.py` to copy more sub-trees, or (b) split into multiple seed scripts. Out of scope here.

---

## Self-Review

**Spec coverage:**

- "Purpose" → Task 9 SKILL.md "When to use" / "When NOT to use" sections.
- "Preconditions and Short-Circuit Behavior" → Tasks 4.1, 4.2, 4.3.
- "Output Contract" (path format, suffix derivation) → Tasks 5, 7.
- "Template" (seven-slot structure, HTML-comment hints) → Task 1.
- "Customization (via the agent-plugins Convention)" → Task 6 (resolve_template), Task 8 (wired into main).
- "Seeding the Home-Scope Template — SessionStart hook" → Tasks 10, 11.
- "Seeding the Home-Scope Template — Codex installer step" → Task 12.
- "Seeding the Home-Scope Template — Skill-helper self-heal" → Task 6.2 (unit) + Task 8 (wired into main).
- "Skill Layout" → file paths used in Tasks 1, 2, 3, 9.
- "SKILL.md" content requirements → Task 9.
- "scripts/handoff.py" responsibilities → Tasks 3, 4, 5, 6, 7, 8.
- "references/templates/handoff.md" → Task 1.
- "Bento Claude Plugin: SessionStart Hook Wiring" → Task 11 (hooks.json edit), Task 14 (rebuild plugins so generated artifacts pick up new files).
- "Codex Installer Change" → Task 12.
- "Tests" — TestHandoffPreconditions / TestSuffixDerivation / TestTemplateResolution / TestSelfHeal / TestPathGeneration / TestSeedHook → Tasks 4, 5, 6, 7, 10.
- "Build Integration and Version Bumping" → Tasks 13, 14.
- "Open Items / Explicit Non-Decisions" → carried forward as plan flexibility (slug derivation rule lives in the agent's prose, not the helper; `--input` accepts both paths and stdin).
- "Non-Negotiable Rules (for the runtime)" → Task 9 SKILL.md "Non-Negotiable Rules" section.
- "References" → kept as cross-references in SKILL.md and the spec itself.

**Placeholder scan:** No TBDs or "implement later" steps. Every step has exact paths, exact code or content, and an exact verification command with expected output.

**Type consistency:** Helper functions are defined once (`HandoffError`, `derive_suffix`, `sanitize_suffix`, `resolve_template`, `self_heal_home_template`, `output_path`) and reused with the same signatures across tasks. Hook script `seed_handoff_template(plugin_root)` is single-use. Tests reference the same names.

**Test coverage:**
- Preconditions: 3 cases (no repo, detached, active expedition) + happy-path passes implicitly via end-to-end tests.
- Suffix derivation: clean, slash, unusual chars, dot/underscore/dash kept; primary-branch slug required and used; non-primary branch ignores slug.
- Template resolution: repo wins, home wins, bundled fallback, XDG default when unset.
- Self-heal: creates when missing; preserves when present; silent no-op when bundled missing.
- Path generation: format match; consecutive timestamps differ.
- End-to-end: file written under tmp root with branch suffix; stdin input works; self-heal happens in real run; primary branch refuses without slug; primary branch uses slug.
- Hook script: first run creates; second run preserves; missing bundled is no-op; unwritable XDG is no-op.
- Codex installer: home seeds; project seeds; existing file preserved.

That maps to every test case the spec listed under "Tests". Coverage appears complete.

**No test failures created by this plan.** Task 14's rebuild runs the full `python3 -m unittest discover` and the `claude plugin validate` step (when available); the green outcome is the gate.
