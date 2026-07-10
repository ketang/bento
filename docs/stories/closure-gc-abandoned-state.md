---
schema_version: 1
title: Closure GCs Abandoned Agent Git State
slug: closure-gc-abandoned-state
status: active
authority: observed
change_resistance: medium
tests_applicable: true
locked_sections:
  - Intent
---

# Closure GCs Abandoned Agent Git State

## Intent
When a repo accumulates branches, worktrees, and stashes left behind by crashed or abandoned agents, the closure skill performs a safe garbage-collection pass over that orphaned state — without touching the calling agent's own work.

## Story
After several agents have run over a week, a repo has five stale worktrees: some from crashed sessions, some from agents whose land-work cleanup never ran. A user invokes closure for a periodic GC pass. The skill dry-runs first, scanning each worktree for liveness signals — recent commits, active processes, recent access times — and surfaces a report of what appears dead. The helper detects that one of the worktrees belongs to the calling agent's own process tree and marks it with `self_invocation: true`, directing the agent to use land-work instead. For the remaining dead worktrees, the agent removes each one in apply mode, deletes its associated branch, and records any uncommitted changes it discarded. After closure completes, the repo's worktree list contains only live work.

## Expected Behavior
- The skill dry-runs before applying any destructive action.
- The helper detects self-invocation and skips the calling agent's own worktree with a directed error.
- Dead worktrees are identified by liveness inference, not just by branch age.
- Uncommitted state discarded during cleanup is recorded.
- The skill does not clean up the calling agent's own work — that is land-work's job.

## Boundaries
- Not a per-task cleanup step; applies only as periodic GC over other agents' state.
- Does not apply to the calling agent's own active or just-finished work.
- Does not interpret abandoned state as "safe to merge" — it only removes dead git state.

## Auditable Claims
- The SKILL.md states: "The helper detects self-invocation … and surfaces a `self_invocation: true` flag plus a pointed apply-mode skip reason directing you to `land-work`."
- The SKILL.md states: "Treat it as periodic GC, not a per-task step."
- Dry-run mode is required before apply mode per the workflow.

## Evidence
### Tests
### Surface
- `skill: closure`
### Docs
- `catalog/skills/closure/SKILL.md`
