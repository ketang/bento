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
After several agents have run over a week, a repo has five stale worktrees: some from crashed sessions, some from agents whose land-work cleanup never ran. A user invokes closure for a periodic GC pass. The skill dry-runs first, scanning each worktree for liveness signals — recent commits, active processes, recent access times — and surfaces a report of what appears dead. The helper detects that one of the worktrees belongs to the calling agent's own process tree and marks it with `self_invocation: true`, directing the agent to use land-work instead. For the remaining dead worktrees, the agent does not hand-write any removal command: every deletion goes through the helper's apply modes (`--apply delete-local-merged-branches`, `--apply delete-local-patch-equivalent-branches`), which remove the clean merged worktree and its branch in the right order. A worktree with uncommitted changes is never force-removed: the helper skips it with the reason `worktree has uncommitted changes` and skips its branch too, so no dirty state is discarded. The agent ends the pass at the repository root on the primary branch, and the repo's worktree list contains only live work.

## Expected Behavior
- The skill dry-runs before applying any destructive action.
- The helper detects self-invocation and skips the calling agent's own worktree with a directed error.
- Dead worktrees are identified by liveness inference, not just by branch age.
- A worktree with uncommitted changes is refused rather than removed, and recorded in the skipped actions with its reason. Uncommitted state is never treated as affirmative liveness evidence either.
- Branch and worktree deletion happens only through the helper's `--apply` modes; the agent never constructs a manual `git branch -D`/`-d` command.
- The pass ends at the repository root on the detected primary branch, not inside a feature-branch worktree.
- The skill does not clean up the calling agent's own work — that is land-work's job.

## Boundaries
- Not a per-task cleanup step; applies only as periodic GC over other agents' state.
- Does not apply to the calling agent's own active or just-finished work.
- Does not interpret abandoned state as "safe to merge" — it only removes dead git state.

## Auditable Claims
- The SKILL.md states: "The helper detects self-invocation … and surfaces a `self_invocation: true` flag plus a pointed apply-mode skip reason directing you to `land-work`."
- The SKILL.md describes closure as sweeping up state left by agents whose `land-work` cleanup did not run — "periodic GC, not a per-task step."
- The SKILL.md Safety rules state: "During a closure GC pass, never construct manual `git branch -D` or `git branch -d` commands." All branch deletion goes through the helper's apply modes.
- Dry-run mode is required before apply mode per the workflow.

## Evidence
### Tests
- `tests/closure/test_closure_scan.py`
### Docs
- `catalog/skills/closure/SKILL.md`
