---
name: swarm
description: |
  Use when multiple ready tasks can be worked in parallel. Triages tasks,
  batches non-overlapping work, launches isolated worktrees, reviews teammate
  plans, lands branches safely, and runs final quality checks.
---

# Swarm

Use this skill when a project has multiple ready tasks that can be worked in
parallel with good isolation.

## Inputs

- The candidate task list, or a documented tracker query that can produce it
- The project's documented tracker workflow
- The project's documented branch, worktree, and landing conventions
- The project's required quality gates and any pre-completion checks

## Deterministic Helpers

This skill includes local helper scripts under `scripts/` for the parts of the
workflow that benefit from stable, repeatable checks:

- `python3 scripts/swarm-discover.py` to emit git-derived defaults plus any
  structured swarm config the repo exposes
- `python3 scripts/swarm-triage.py --input <json>` to batch normalized task
  data into the currently unblocked frontier, wait queues, and skips
- `python3 scripts/swarm-worktree-verify.py` to verify the current checkout is
  the expected linked worktree on the expected branch

These helpers require `python3`. If `python3` is unavailable on the machine,
fall back to the prose workflow in this skill and perform the checks manually.

Keep tracker fetching outside these helpers. Use the project's tracker workflow
to gather tasks, then normalize them into the triage input format.

## Companion Skills

- If the project uses Beads, use `beads-issue-flow` for claiming and closing.
- If the project uses GitHub Issues, use `github-issue-flow`.
- Use `launch-work` for the exact branch and worktree bootstrapping rules.
- Use `land-work` for the final landing procedure when project docs do not
  define a stricter swarm-specific landing flow.

## Phase 0: Discover Project Rules

Before triage, read the project's local instructions and determine:

- how to list and inspect ready tasks
- how active work is claimed
- how branches and worktrees are named
- which quality gates apply per task and after all merges
- whether a pre-completion checklist or skill is required
- whether the tracker exposes explicit task dependencies
- how completed branches land on the integration branch
- whether post-land hooks are required

When the project exposes a structured swarm config, run:

```bash
python3 scripts/swarm-discover.py
```

Use the output as the deterministic base layer, then fill any remaining gaps
from repo docs.

If the project does not document these items clearly enough to swarm safely,
stop and ask the user to narrow the scope or clarify the workflow.

## Phase 1: Triage

1. Resolve the candidate task set from explicit task IDs or the documented
   tracker's ready-work query.
2. Inspect each task closely enough to understand scope, likely files, and
   whether it is small enough for one teammate.
3. Identify tasks already in progress and do not pick them up.
4. Predict likely file overlap across the candidate tasks and with any active
   work already underway.
5. Batch only tasks that appear meaningfully isolated from one another.
6. Sequence tasks that touch shared hotspots such as:
   - central schemas
   - shared configuration or type definitions
   - generated outputs
   - high-churn framework entrypoints
7. If the project tracker exposes explicit dependencies, do not treat the work
   as a flat queue. Spawn only the currently unblocked frontier, then recompute
   readiness after each landed batch.
8. Skip tasks that are too large, ambiguous, or coupled for parallel execution.
9. Present the triage plan and wait for approval before spawning teammates.

When the project can supply normalized task data, prefer using:

```bash
python3 scripts/swarm-triage.py --input triage.json
```

Expected input shape:

```json
{
  "tasks": [
    {
      "id": "task-123",
      "title": "Implement feature",
      "priority": 10,
      "paths": ["pkg/a", "pkg/b/file.go"],
      "dependencies": ["task-100"],
      "in_progress": false,
      "too_large": false,
      "ambiguous": false
    }
  ],
  "landed_task_ids": ["task-100"],
  "active_paths": ["shared/schema.graphql"],
  "hotspots": ["shared/schema.graphql"],
  "max_parallel": 4,
  "batch_limit": 20
}
```

The script stays tracker-agnostic. Tracker-specific skills are responsible for
collecting tasks and converting them into this format.

## Phase 2: Teammate Launch

For each approved task:

1. Create exactly one branch and exactly one worktree for that task.
2. Require the teammate to do implementation only from that worktree.
3. Include the task details, expected scope, likely overlap risks, and required
   quality gates in the prompt.
4. Require the teammate to stop and report back if the task is broader or more
   coupled than expected.

The teammate must verify both working directory and branch before doing any
implementation:

```bash
python3 scripts/swarm-worktree-verify.py --require-linked-worktree
```

Reject any teammate setup that cannot show they are inside the intended
worktree on the intended branch.

## Phase 3: Plan Review

Review each teammate plan for:

- correct scope with no opportunistic extras
- explicit worktree path and branch verification
- correct quality gates for the files they expect to change
- test coverage appropriate to the task
- no unresolved overlap with active teammates
- any required pre-completion checklist or review step

Reject plans that reference the primary checkout instead of a dedicated
worktree, or that do not explain how the task will be verified.

## Phase 4: Monitor and Land

As teammates finish:

1. Verify the promised quality gates actually ran and passed.
2. Verify any required pre-completion step was completed.
3. Land one completed branch at a time using the project's documented landing
   workflow.
4. If conflicts arise, either resolve them carefully or send the task back for
   rebase.
5. Run any documented post-land hooks before considering the task complete.
6. Close or update the tracker item only after the verified landing succeeds.
7. Clean up the task branch and worktree only after the work is safely landed.

Never shut down or discard a teammate's work before it is either landed or
explicitly deferred.

## Phase 5: Final Validation

After all approved tasks are landed:

1. Run the project's full aggregate quality gate.
2. Confirm any generated assets, schemas, or walkthrough artifacts are updated.
3. Summarize what landed, what was deferred, and any follow-up risks.

## Non-Negotiable Rules

- Do not implement directly on the primary branch.
- Do not treat tracker-specific commands as universal; follow project docs.
- Do not parallelize tasks with likely overlap just to maximize throughput.
- Do not close tracker work before the landing is verified.
- Do not silently improvise repo-specific policy that the project has not
  documented.
