---
name: swarm
description: Use when multiple ready tasks can be worked in parallel — triage, batch non-overlapping work, launch isolated worktrees, review plans, land safely.
recommended_model: high
---

# Swarm

## Model Guidance

Recommended model: high — triage, overlap prediction, and multi-teammate
coordination degrade sharply on smaller models.

Use this skill when a project has multiple ready tasks that can be worked in
parallel with good isolation.

## Inputs

- The candidate task list, or a documented tracker query that can produce it
- The project's documented tracker workflow
- The project's documented branch, worktree, and landing conventions
- The project's required quality gates and any pre-completion checks

## Deterministic Helpers

This skill includes local helper scripts under `swarm/scripts/`:

- `swarm/scripts/swarm-discover.py` — git-derived defaults plus any structured
  swarm config the repo exposes
- `swarm/scripts/swarm-triage.py --input <json>` — batch normalized task data
  into unblocked frontier, wait queues, and skips. Run `--help` for the input
  schema and output category enum.
- `swarm/scripts/swarm-worktree-verify.py` — verify the current checkout is
  the expected linked worktree on the expected branch

Invoke these helpers by script path, not `python3 <script>`, so approvals stay
scoped to the script. They require `python3` on `PATH`. If `python3` is
unavailable, fall back to the prose workflow and perform checks manually.

Keep tracker fetching outside these helpers. Use the project's tracker workflow
to gather tasks, then normalize them into the triage input format.

## Continuation State

If a batch overflows the current run, persist remaining task IDs in
runtime-local state so a later invocation can resume without re-querying the
tracker. See `swarm/references/continuation-state.md` for runtime state roots,
`continue.txt`/`handoff.md` formats, and the Claude Code session-ID pre-flight.

## Companion Skills

- If the project uses Beads, use `beads-issue-flow` for claiming and closing.
- If the project uses GitHub Issues, use `github-issue-flow`.
- Use `launch-work` for the exact branch and worktree bootstrapping rules.
- Use `land-work` for the final landing procedure when project docs do not
  define a stricter swarm-specific landing flow.

## Phase 0: Discover Project Rules

Before triage, read the project's local instructions and determine:

- how to list, inspect, and claim ready tasks
- which agent runtime is orchestrating the swarm and its teammate launch model
- how branches and worktrees are named
- which quality gates apply per task and after all merges
- whether a pre-completion checklist or skill is required
- whether the tracker exposes explicit task dependencies
- how completed branches land on the integration branch
- whether post-land hooks are required

When the project exposes a structured swarm config, run the discovery helper
for the current runtime:

```bash
swarm/scripts/swarm-discover.py --runtime claude   # or --runtime codex
```

This loads the matching runtime-specific config if present and otherwise falls
back to the shared `swarm-config.json` at the repo root. Use the output as the
deterministic base layer, then fill remaining gaps from repo docs.

If the project does not document these items clearly enough to swarm safely,
stop and ask the user to narrow the scope or clarify the workflow.

## Phase 1: Triage

1. Resolve the candidate task set from explicit task IDs or the documented
   tracker's ready-work query.
2. Inspect each task closely enough to understand scope, likely files, and
   whether it is small enough for one teammate.
3. Skip tasks already in progress, too large, ambiguous, or coupled for
   parallel execution.
4. Predict file overlap across candidates and with any active work. Batch only
   tasks that appear meaningfully isolated. Sequence tasks that touch shared
   hotspots (central schemas, shared config/types, generated outputs,
   high-churn framework entrypoints).
5. If the tracker exposes explicit dependencies, spawn only the currently
   unblocked frontier, then recompute readiness after each landed batch — not
   a flat queue.
6. When a teammate finishes and a slot opens, re-triage the remaining
   candidates against current active paths, hotspots, landed IDs, and newly
   unblocked dependencies before backfilling. Do not refill if every remaining
   task is still blocked or conflicting.
7. Present the triage plan and wait for approval before spawning teammates.

When the project can supply normalized task data, prefer:

```bash
swarm/scripts/swarm-triage.py --input triage.json
```

Run `swarm-triage.py --help` for the input schema and the output categories
(`parallel_batch`, `wait_queue`, `overflow`, `skipped`,
`deferred_due_to_dependencies`, `deferred_due_to_active_overlap`). The script
is tracker-agnostic; tracker-specific skills convert tasks into this format.

## Phase 2: Teammate Launch

Use the runtime's managed multi-agent flow, not ad hoc background workers:

- Claude Code: `TeamCreate` + one `TaskCreate` per approved item + `Agent`
  with both `team_name` and a descriptive `name` set.
- Codex: `spawn_agent` per approved item, then `send_input` / `wait_agent` /
  `close_agent` for lifecycle.

For each approved task: exactly one branch, exactly one worktree, and the
prompt must include task details, expected scope, overlap risks, and required
quality gates. Require the teammate to stop and report back if the task is
broader or more coupled than expected.

The teammate must verify working directory and branch before any edits:

```bash
swarm/scripts/swarm-worktree-verify.py --require-linked-worktree
```

Reject any teammate setup that cannot show they are inside the intended
worktree on the intended branch.

## Phase 3: Plan Review

Review each teammate plan for correct scope (no opportunistic extras), explicit
worktree+branch verification, correct quality gates, test coverage appropriate
to the task, no unresolved overlap with active teammates, and any required
pre-completion step. Reject plans that reference the primary checkout or do
not explain how the task will be verified.

## Phase 4: Monitor and Land

Land one completed branch at a time using the project's documented landing
workflow (see `land-work` unless project docs define a stricter flow):

1. Verify the promised quality gates actually ran and passed, plus any
   required pre-completion step.
2. Land the branch; resolve conflicts carefully or send back for rebase.
3. Run any documented post-land hooks.
4. Close or update the tracker item only after the verified landing.
5. Close the teammate and clean up branch + worktree only after the work is
   safely landed or explicitly deferred. Never discard a teammate's work
   before then.

When the last Claude Code teammate in the batch is done, delete the team. In
Codex, close each spawned agent when its task is landed or deferred.

## Phase 5: Final Validation

After all approved tasks are landed:

1. Run the project's full aggregate quality gate.
2. Confirm generated assets, schemas, or walkthrough artifacts are updated.
3. Summarize what landed, what was deferred, and any follow-up risks.
