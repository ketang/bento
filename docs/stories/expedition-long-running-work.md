---
schema_version: 1
title: Expedition Coordinates Long-Running Interdependent Work
slug: expedition-long-running-work
status: active
authority: observed
change_resistance: medium
tests_applicable: false
locked_sections:
  - Intent
---

# Expedition Coordinates Long-Running Interdependent Work

## Intent
When a project requires weeks of interdependent work across multiple sessions and agents, the expedition skill creates a named base branch, manages a serial landing lease for task branches off that base, and preserves failed experiments so nothing is lost.

## Story
A user wants to rewrite the bento plugin packaging system — a body of work spanning schema changes, CLI updates, install flow changes, and documentation. Individual tasks are too interconnected for independent swarm execution. The user invokes expedition with a name, goal, and initial task decomposition. The skill creates a base branch from the primary branch and a dedicated linked worktree. Each task gets its own branch cut from the base (`<expedition>-<nn>-<slug>`), and a serial landing lease ensures only one task merges to the base at a time, preventing merge conflicts. When an experimental approach fails, the skill creates an experiment branch (`<expedition>-exp-<nn>-<slug>`) and preserves it rather than discarding the work. At each session end, the skill writes a handoff file inside the base branch so the next session knows exactly where to resume.

## Expected Behavior
- A named base branch is created from the primary branch.
- Task branches follow the `<expedition>-<nn>-<slug>` naming convention.
- A serial landing lease enforces orderly merges to the base branch.
- Failed experiments are preserved on `<expedition>-exp-<nn>-<slug>` branches.
- Session handoff state is written inside the base branch, not to an ephemeral temp file.
- All worktrees (base, tasks, experiments) live as siblings under a common root.

## Boundaries
- Does not apply to work that can be cleanly parallelized without a shared base — use swarm for that.
- Does not use the handoff skill's `/tmp/` file for session state — expedition maintains its own in-branch protocol.
- Does not fast-forward or squash-merge task branches to the base.

## Auditable Claims
- The SKILL.md documents branch naming patterns: base `<expedition>`, task `<expedition>-<nn>-<slug>`, experiment `<expedition>-exp-<nn>-<slug>`.
- The SKILL.md states worktrees are siblings under the same root: `~/.local/share/worktrees/<repo>/`.
- A serial landing lease is a documented hard invariant.

## Evidence
### Tests
### Surface
- `skill: expedition`
### Docs
- `catalog/skills/expedition/SKILL.md`
