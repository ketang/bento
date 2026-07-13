---
schema_version: 1
title: Swarm Batches and Executes Parallel Tasks
slug: swarm-parallel-task-batching
status: active
authority: observed
change_resistance: medium
tests_applicable: false
locked_sections:
  - Intent
---

# Swarm Batches and Executes Parallel Tasks

## Intent
When a project has multiple ready tasks with good isolation between them, the swarm skill triages the task list, batches non-overlapping work, and launches isolated worktrees to execute tasks in parallel.

## Story
A user has a backlog of ready tasks — several bug fixes, a documentation update, and two independent feature additions. Rather than working through them serially in a single session, the user invokes swarm. The skill runs the discover helper to identify defaults and any structured swarm config the repo exposes, then runs the triage helper against the normalized task list to sort tasks into an unblocked frontier, wait queues, and skips. For the unblocked frontier, the skill launches isolated worktrees — one per task — and assigns each to an agent subagent or teammate. Each agent follows the repo's full launch/land lifecycle. After each task lands, swarm's post-land hook runs to update shared state. The user observes multiple tasks landing in rapid succession without merge conflicts, because the work was genuinely non-overlapping.

## Expected Behavior
- The discover helper produces git-derived defaults and repo-specific swarm config.
- The triage helper partitions tasks into unblocked frontier, wait queues, and skips, with reasons.
- Each unblocked task runs in its own isolated linked worktree.
- Overlapping tasks are deferred to a wait queue, not run concurrently.
- Post-land hooks update shared state after each successful landing.
- The landing target branch defaults to the detected primary branch unless overridden.

## Boundaries
- Applies only when multiple tasks can run in parallel with good isolation.
- Does not attempt to parallelize tasks with shared-state dependencies.
- Does not bypass the repo's per-task launch and land lifecycle.

## Auditable Claims
- `swarm/scripts/swarm-discover.py` produces git-derived defaults plus any structured swarm config.
- `swarm/scripts/swarm-triage.py --input <json>` partitions tasks into frontier, wait queues, and skips.
- `swarm/scripts/swarm-worktree-verify.py` verifies the checkout is the expected linked worktree on the expected branch.
- `swarm/scripts/swarm-post-land.py` runs a named post-land hook after a successful land.

## Evidence
### Tests
### Surface
- `skill: swarm`
### Docs
- `catalog/skills/swarm/SKILL.md`
