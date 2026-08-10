---
schema_version: 1
title: Swarm Batches and Executes Parallel Tasks
slug: swarm-parallel-task-batching
status: active
authority: observed
change_resistance: medium
tests_applicable: true
locked_sections:
  - Intent
---

# Swarm Batches and Executes Parallel Tasks

## Intent
When a project has multiple ready tasks with good isolation between them, the swarm skill triages the task list, batches non-overlapping work, and launches isolated worktrees to execute tasks in parallel.

## Story
A user has a backlog of ready tasks — several bug fixes, a documentation update, and two independent feature additions. Rather than working through them serially in a single session, the user invokes swarm. The skill runs the discover helper for the current runtime to identify git-derived defaults and the runtime-specific swarm config — under the `codex` runtime it also resolves the teammate model and reasoning effort, which the `claude` runtime leaves unset — then runs the triage helper against the normalized task list to sort tasks into a parallel batch, a wait queue, an overflow list, and skips. For the parallel batch, the skill launches isolated worktrees — one per task — and assigns each to a teammate. Teammates implement and verify but do not land: their prompts forbid invoking land-work, merging or pushing to the primary branch, closing the tracker issue, or removing their worktree. When a branch is complete, the lead runs land-work for it — one branch at a time — and then, if a post-land hook is configured for this swarm, runs it to rebase the landing target onto primary before re-triaging the remaining branches. The user observes multiple tasks landing in rapid succession without merge conflicts, because the work was genuinely non-overlapping.

## Expected Behavior
- The discover helper produces git-derived defaults and the runtime-specific swarm config; teammate model and reasoning effort are resolved only under the `codex` runtime.
- The triage helper partitions tasks into a parallel batch, wait queue, overflow, and skips, with reasons.
- Each batched task runs in its own isolated linked worktree, verified before any edit.
- Overlapping tasks are deferred to a wait queue, not run concurrently.
- Teammates never land their own work; the lead runs land-work for every completed branch, one branch at a time.
- When a post-land hook is configured, it runs after each successful landing; a failing hook stops further landings.
- The landing target branch defaults to the detected primary branch unless overridden.

## Boundaries
- Applies only when multiple tasks can run in parallel with good isolation.
- Does not attempt to parallelize tasks with shared-state dependencies.
- Does not bypass the repo's per-task launch lifecycle.
- Does not delegate landing to teammates; landing stays with the lead.

## Auditable Claims
- `swarm/scripts/swarm-discover.py --runtime <claude|codex>` produces git-derived defaults and the runtime-specific swarm config; the `teammate_model`, `teammate_reasoning_effort`, and `teammate_config_path` fields are populated only when `--runtime codex` is passed, and are null otherwise.
- `swarm/scripts/swarm-triage.py --input <json>` partitions tasks into `parallel_batch`, `wait_queue`, `overflow`, `skipped`, and deferred buckets with reasons.
- `swarm/scripts/swarm-worktree-verify.py --require-linked-worktree` must exit 0 before any edit in a teammate worktree.
- `swarm/scripts/swarm-post-land.py --hook <name> --landing-target <branch> --primary <branch> --apply` is run by the lead after land-work completes when a hook is configured; a hook failure stops further landing. The only defined hook is `rebase-landing-target-onto-primary`, which rebases the landing target onto the primary branch.
- The SKILL.md states: "Teammates do not land their own work. The lead runs `bento:land-work` for every completed branch."

## Evidence
### Tests
- `tests/swarm/test_swarm_scripts.py`
- `tests/swarm/test_swarm_discover.py`
- `tests/swarm/test_swarm_post_land.py`
### Surface
- `skill: swarm`
### Docs
- `catalog/skills/swarm/SKILL.md`
- `catalog/skills/swarm/CLAUDE.md`
- `catalog/skills/swarm/CODEX.md`
