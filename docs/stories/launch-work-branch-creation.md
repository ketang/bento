---
schema_version: 1
title: Launch Work Creates Branch and Worktree
slug: launch-work-branch-creation
status: active
authority: observed
change_resistance: medium
tests_applicable: true
locked_sections:
  - Intent
---

# Launch Work Creates Branch and Worktree

## Intent
When an agent is about to make any code or file edit, launch-work creates an isolated branch and linked worktree so the work never touches the primary branch directly.

## Story
An agent receives a task — fix a bug, add a skill, update docs. Before touching a single file, the launch-work skill fires. It reads the repo's local instructions to find the documented branch and worktree conventions, optionally claims a tracker issue, then runs the bootstrap helper in dry-run mode to preview the branch name and worktree path. Once the agent confirms the target is correct, it re-runs with `--apply` to materialize the branch and linked worktree. It then symlinks the primary checkout's `.claude/settings.json` and `.claude/settings.local.json` into the new worktree — but only those that are untracked there, since a linked worktree contains only git-tracked files — runs any project `pre` lifecycle extension hooks, and bootstraps dependencies. From that point forward, all edits happen inside the isolated worktree; where automated coverage is feasible, a failing test is committed before the implementation. The primary branch is left untouched until land-work is invoked.

## Expected Behavior
- The skill is invoked before any edit to files inside the repository working tree, even trivial ones; writes to `/tmp`, scratch space, and agent memory directories are exempt.
- A new branch is created from the primary branch head.
- A linked worktree is created at the path determined by the repo's worktree placement conventions.
- The agent's working directory switches to the new worktree.
- If a tracker issue exists, it is claimed or updated to the active-work status.
- Dry-run output is shown before `--apply` is used.
- Project `pre` lifecycle extension hooks run after worktree verification; a hook exiting 75 halts for human handoff.
- For new work or a behavioral change with feasible automated coverage, a failing test is committed before implementation; where coverage is infeasible, that is stated explicitly rather than skipped silently.
- Dependencies are bootstrapped in the new worktree before implementation begins.

## Boundaries
- Does not perform product-code edits itself; its own writes are limited to workspace setup — creating the branch and worktree, symlinking the primary checkout's untracked `.claude/` settings files, and installing dependencies.
- Does not apply to tracker-only mutations (creating, updating, or closing issues without touching files), or to out-of-tree outputs such as `/tmp`, scratch files, and agent memory directories.
- Does not handle landing; that is land-work's responsibility.

## Auditable Claims
- `launch-work/scripts/launch-work-bootstrap.py` accepts `--branch` and `--worktree` flags and supports a dry-run mode before `--apply`.
- `launch-work/scripts/launch-work-verify.py` accepts `--expected-branch`, `--expected-worktree`, and `--require-linked-worktree` to confirm the checkout matches intent.
- The SKILL.md hard-trigger description reads: "Hard trigger — always invoke before any edit to files inside a repository working tree; non-repo outputs (/tmp, scratch, memory dirs) and tracker-only mutations are exempt. Creates branch+worktree. Never skip for small changes."
- `launch-work/scripts/run-lifecycle-extensions.py` runs project `pre` and `post` hooks, backed by `launch-work/scripts/lifecycle_extensions.py`.
- Worktree placement is governed by `launch-work/references/worktree-location.md`, and dependency bootstrap by `launch-work/references/dependency-bootstrap.md`.

## Evidence
### Tests
- `tests/launch_work/test_launch_work_scripts.py`
- `tests/launch_work/test_lifecycle_extensions_cli.py`
- `tests/launch_work/test_lifecycle_extensions_run_hooks.py`
### Surface
- `skill: launch-work`
### Docs
- `catalog/skills/launch-work/SKILL.md`
- `catalog/skills/launch-work/references/worktree-location.md`
- `catalog/skills/launch-work/references/dependency-bootstrap.md`
