---
schema_version: 1
title: Expedition Coordinates Long-Running Interdependent Work
slug: expedition-long-running-work
status: active
authority: observed
change_resistance: medium
tests_applicable: true
locked_sections:
  - Intent
---

# Expedition Coordinates Long-Running Interdependent Work

## Intent
When a project requires weeks of interdependent work across multiple sessions and agents, the expedition skill creates a named base branch, manages a serial landing lease for task branches off that base, and preserves failed experiments so nothing is lost.

## Story
A user wants to rewrite the bento plugin packaging system — a body of work spanning schema changes, CLI updates, install flow changes, and documentation. Individual tasks are too interconnected for independent swarm execution. The user invokes expedition with a name, goal, and initial task decomposition. The skill creates a base branch from the primary branch and a dedicated linked worktree. Each task gets its own branch cut from the base (`<expedition>-<nn>-<slug>`), and a serial landing lease ensures only one task merges to the base at a time, preventing merge conflicts. Experiments are cut up front rather than after the fact: `start-task --kind experiment` creates an experiment branch (`<expedition>-exp-<nn>-<slug>`), and if the approach fails the branch and its worktree are preserved rather than discarded. Performance experiments get their own pattern (`<expedition>-perfexp-<nn>-<slug>`) and are limited to one active at a time, because parallel performance measurements contaminate each other on shared hardware. At each session end, the skill writes a handoff file inside the base branch so the next session knows exactly where to resume.

## Expected Behavior
- A named base branch is created from the primary branch.
- Task branches follow the `<expedition>-<nn>-<slug>` naming convention.
- A serial landing lease enforces orderly merges to the base branch.
- Failed experiments are preserved on `<expedition>-exp-<nn>-<slug>` branches and never merged into the base branch.
- At most one performance optimization experiment (`<expedition>-perfexp-<nn>-<slug>`) is active per expedition at a time.
- Session handoff state is written inside the base branch, not to an ephemeral temp file.
- All worktrees (base, tasks, experiments) live as siblings under a common root.

## Boundaries
- Does not apply to work that can be cleanly parallelized without a shared base — use swarm for that.
- Does not use the handoff skill's `/tmp/` file for session state — expedition maintains its own in-branch protocol.
- Does not merge failed experiment branches into the base branch.

## Auditable Claims
- The SKILL.md documents four branch naming patterns: base `<expedition>`, task `<expedition>-<nn>-<slug>`, experiment `<expedition>-exp-<nn>-<slug>`, and performance optimization experiment `<expedition>-perfexp-<nn>-<slug>`.
- `expedition/scripts/expedition.py start-task --kind task|experiment|perf-experiment` creates the next numbered branch and worktree, and rejects a `perf-experiment` while another is active.
- The SKILL.md states worktrees are siblings under the same root: `~/.local/share/worktrees/<repo>/`.
- A serial landing lease is one of the documented hard invariants: "One landing lease per expedition."

## Evidence
### Tests
- `tests/expedition/test_expedition_scripts.py`
### Docs
- `catalog/skills/expedition/SKILL.md`
