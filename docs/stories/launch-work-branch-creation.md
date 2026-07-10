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
An agent receives a task — fix a bug, add a skill, update docs. Before touching a single file, the launch-work skill fires. It reads the repo's local instructions to find the documented branch and worktree conventions, optionally claims a tracker issue, then runs the bootstrap helper in dry-run mode to preview the branch name and worktree path. Once the agent confirms the target is correct, it re-runs with `--apply` to materialize the branch and linked worktree. From that point forward, all edits happen inside the isolated worktree, with the primary branch left untouched until land-work is invoked.

## Expected Behavior
- The skill is invoked before any file edit, even trivial ones.
- A new branch is created from the primary branch head.
- A linked worktree is created at the path determined by the repo's worktree placement conventions.
- The agent's working directory switches to the new worktree.
- If a tracker issue exists, it is claimed or updated to the active-work status.
- Dry-run output is shown before `--apply` is used.

## Boundaries
- Does not perform any file edits itself; only sets up the workspace.
- Does not apply to tracker-only mutations (creating, updating, or closing issues without touching files).
- Does not handle landing; that is land-work's responsibility.

## Auditable Claims
- `launch-work/scripts/launch-work-bootstrap.py` accepts `--branch` and `--worktree` flags and supports a dry-run mode before `--apply`.
- `launch-work/scripts/launch-work-verify.py` accepts `--expected-branch`, `--expected-worktree`, and `--require-linked-worktree` to confirm the checkout matches intent.
- The SKILL.md hard-trigger description reads: "always invoke before any code or file edits, even small ones."

## Evidence
### Tests
### Surface
- `skill: launch-work`
### Docs
- `catalog/skills/launch-work/SKILL.md`
