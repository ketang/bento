# Expedition uses swarm — design

Date: 2026-04-22
Scope: catalog + plugins copies of the `expedition` and `swarm` skills in the bento repo.

## Goal

Let an expedition run its task branches in parallel, swarm-style, instead of
one at a time. Generalize the `swarm` skill so it works both against the
primary branch (today's behavior, unchanged) and against an expedition base
branch (new behavior). Expedition becomes swarm-by-default; the old serial
invariant is deleted except for performance optimization experiments.

## Why

Today, expedition forbids more than one active task branch per expedition.
That serialization is appropriate for the fraction of tasks that share hot
state, but it blocks parallel progress on the many tasks within an expedition
that do not overlap. Swarm already knows how to triage, launch, and land
parallel work; the only thing stopping it from serving expeditions is that its
landing target is hardcoded to the primary branch.

## Non-goals

- Running multiple expeditions in parallel — already allowed today, unchanged.
- Automating conflict resolution inside the expedition base branch beyond what
  `land-work` already does.
- Supporting parallel performance optimization experiments. Those stay serial
  among themselves by design, to avoid measurement contamination on shared
  hardware.

## Architecture

### Swarm generalization

Swarm gains two optional inputs, both defaulted so primary-branch swarms see
zero behavior change:

- **Landing target branch.** Default: the detected primary branch. When set,
  each completed teammate branch is landed onto this branch instead of
  primary. Exposed via `--landing-target` on the swarm helpers and in the
  prose workflow.
- **Post-land hook.** Default: none. A short enum of named hooks that swarm
  knows how to run after each successful land. Initial enum:
  - `rebase-landing-target-onto-primary` — used by expedition to keep the base
    branch up to date after each task merges.

Swarm internals change in two places only:

1. Phase 4 "Monitor and Land" merges onto `<landing-target>` instead of
   primary. The prose is updated to reference "the landing target" instead of
   "the primary branch."
2. After a successful land, swarm runs the post-land hook if one is set.

Swarm triage, teammate launch, plan review, serial-landing-lease, and final
validation phases are unchanged.

### Expedition workflow model, rewritten

Serial task execution is replaced with swarm-by-default.

**Branches.** Branch names keep today's shape:

- `<expedition>-<nn>-<slug>` — task
- `<expedition>-exp-<nn>-<slug>` — regular experiment
- `<expedition>-perfexp-<nn>-<slug>` — performance optimization experiment

**Parallelism rules.**

- Tasks: many in flight at once. Cut from the current base tip at launch.
- Regular experiments: many in flight at once, same as tasks.
- Performance optimization experiments: strictly serial. At most one active
  performance optimization experiment per expedition at a time. Other
  in-flight tasks and regular experiments do not block it, and it does not
  block them. Hardware contention across kinds is managed by the coordinator,
  not by this rule.

**Quality bar.** Experiment branches — regular and performance optimization
alike — are held to the same production-quality bar as task branches. An
experiment is called an experiment because the hypothesis may not pan out,
not because the coding standard is lower. No measurement scaffolding, debug
prints, stubbed tests, or disabled logging are left behind. The implementing
agent is not done until the branch is production-quality, whether the
experiment is kept or failed.

**Rebase rules.**

- The expedition base branch rebases onto primary. Unchanged.
- Any kept branch — task, regular experiment, or performance optimization
  experiment — rebases exactly once, at land time, onto the current base tip.
  This is the only exception to the previous "branches never rebase" rule.
- In-flight branches are not proactively rebased when the base moves. They
  catch up at their own land time.
- Failed experiment branches (regular or performance optimization) do not
  rebase. They are preserved as-is.

**Landing cycle per kept branch (task, regular experiment, or performance
optimization experiment).**

The expedition coordinator holds one landing lease per expedition, serial,
enforced in `state.json`. For each completing branch:

1. Acquire the lease.
2. Rebase the branch onto the current base tip.
3. Merge the branch into base.
4. Rebase base onto primary. (This is the `rebase-landing-target-onto-primary`
   post-land hook, invoked via the generalized swarm machinery.)
5. Update `state.json`, append to `log.md`, rewrite `handoff.md` on the base
   worktree.
6. Release the lease.
7. Re-triage and decide whether to launch a replacement branch.

**Failed experiment cycle.** Acquire lease, preserve the branch and worktree,
update state, append to log, release lease. Steps 2–4 are skipped.

### Expedition as swarm caller

Expedition does not delegate its whole workflow to the `swarm` skill, because
its triage input is the expedition plan rather than a tracker query, and its
session-handoff model is richer. What expedition reuses from swarm:

- `swarm-triage.py` for overlap and isolation logic, called with the
  expedition-scoped candidate list derived from `plan.md`.
- `swarm-worktree-verify.py` as the teammate pre-edit check, unchanged.
- The generalized swarm landing-target + post-land-hook machinery for the
  actual merge-and-rebase sequence. Expedition invokes it with
  `--landing-target=<expedition>` and
  `--post-land-hook=rebase-landing-target-onto-primary`.

Swarm Phase 2 teammate-launch prose gets a small rewrite so teammates land on
"the landing target" rather than "primary" — that one rewrite covers both
primary-branch swarms and expedition swarms.

## Durable state

### Coordinator session model

One session owns the expedition at a time: the session running the expedition
skill in the base worktree. The coordinator is the only session that writes
to `docs/expeditions/<expedition>/*`, holds the landing lease, launches
teammates, and runs `close-task`. Teammates commit only to their own task
branch; they never touch expedition docs.

### `state.json` schema additions

- `active_branches`: array of `{branch, kind, worktree, launched_at}`.
  Replaces today's single-active-slot assumption.
- `kind`: one of `task`, `experiment`, `perf-experiment`.
- `landing_lease`: `{held_by_branch, acquired_at}` or null.

### `handoff.md` and `log.md`

`handoff.md` continues to describe one-shot resume context and gains a
"currently in flight" section rendered from `active_branches`. `log.md` stays
append-only and sequential, written only by the coordinator at land time (or
at failed-experiment preservation time).

### Helper changes

- `expedition.py start-task` gains `--kind={task,experiment,perf-experiment}`
  with default `task`. Refuses to launch a `perf-experiment` while another
  `perf-experiment` is active. Other kinds launch freely regardless of
  current active branches.
- `expedition.py close-task` acquires the landing lease before it merges.
  Kept-task outcome: rebase branch onto base, merge, run post-land hook to
  rebase base onto primary, update state, release lease. Failed-experiment
  outcome: preserve branch, update state, release lease. Refuses if the lease
  is held by a different branch.
- `expedition.py verify` unchanged in spirit — already checks that the
  current worktree matches base or an active task worktree.
- `expedition.py finish` unchanged.
- `expedition.py discover` gains reconciliation output: it lists stale
  entries in `active_branches` (worktree missing or teammate session dead)
  and reports them to the resuming coordinator. It does not auto-prune.
  The coordinator decides per-branch whether the work is recoverable.

## Rules being deleted from expedition SKILL.md

- Hard invariant "Only one active task or experiment branch may exist for an
  expedition at a time."
- Hard invariant "A new task branch cannot be created until the previous kept
  task is merged into the base branch and the base branch has rebased onto
  the primary branch."
- Hard invariant "Task and experiment branches never rebase." Replaced with
  a narrower rule for performance optimization experiments only.
- Non-negotiable "Do not create a new expedition task branch while an active
  task branch still exists for that expedition."

## Rules being added to expedition SKILL.md

- One landing lease per expedition. Tasks and regular experiments merge
  serially into base even though they run in parallel.
- Only the coordinator writes to durable docs on base. Teammates never commit
  to `docs/expeditions/<expedition>/*`.
- A task or regular experiment branch rebases at most once, at land time,
  onto current base tip.
- At most one active performance optimization experiment per expedition.

## Migration

Existing expeditions may have old-format `state.json` with a single active
slot. On first read by the new `expedition.py`:

- If `active_branches` is absent but an old `current_task` field exists,
  migrate it to a single-entry `active_branches` array with `kind=task`.
- `landing_lease` defaults to null.
- The migrated shape is written back on the next state update, not eagerly,
  so a read-only session does not rewrite state.

Swarm rollout: both new parameters are optional with primary-branch defaults.
Existing swarm invocations stay identical. `land-work` itself does not need to
know about landing targets as long as swarm passes the correct branch as the
merge target.

## Test and verification strategy

- Unit-level: `expedition.py` state migration (old format → new format),
  `start-task --kind=perf-experiment` refuses when a performance optimization
  experiment is active, `close-task` lease acquisition refuses conflicting
  holders.
- Integration-level: a fixture expedition with three tasks runs swarm-style,
  each lands with the post-land rebase hook, base advances past primary after
  each land.
- Regression: an existing swarm invocation against primary with no new flags
  produces byte-identical behavior (merge target, phase transitions) to the
  pre-change swarm.

## Open items

None identified at spec time. Any new open items will be captured in the
implementation plan.
