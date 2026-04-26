---
name: expedition
description: Use when a large body of mostly interdependent work should run as a named expedition on its own long-lived base branch, with parallel task branches off a shared base branch with one landing lease, durable in-branch plan/log/handoff files, and preserved failed experiments.
recommended_model: high
---

# Expedition

## Model Guidance

Recommended model: high.

Use a high-capability model because this skill coordinates long-lived git
state, branch-local durable notes, and repeated handoffs across fresh agent
sessions.

Use this skill when the user wants an "expedition" rather than a one-off task:

- one named base branch created from the primary branch
- parallel task branches cut from that base branch; a serial landing lease keeps merges orderly
- occasional failed experiments that must be preserved but not merged
- a stronger session-handoff protocol than ad hoc pasted prompts

## Inputs

- The expedition name
- The primary goal and success criteria
- The intended task decomposition, or enough context to write one
- The repo's primary branch, if it differs from the detected default
- The repo's verification gates
- The linked-worktree location. Follow
  `../launch-work/references/worktree-location.md`. The expedition base
  worktree and all task and experiment worktrees must live under the same
  durable root — task worktrees are created as siblings of the base worktree.
  With the shared default, the base worktree is
  `~/.local/share/worktrees/<repo>/<expedition>` and task worktrees land at
  `~/.local/share/worktrees/<repo>/<task-branch>`.

## Workflow Model

An expedition is a long-lived serial program of work:

- Base branch: `<expedition>`
- Base worktree: one dedicated linked worktree for that branch
- Task branch: `<expedition>-<nn>-<slug>`
- Experiment branch: `<expedition>-exp-<nn>-<slug>`
- Performance optimization experiment branch: `<expedition>-perfexp-<nn>-<slug>`

Hard invariants:

- The base branch rebases onto the primary branch exactly once, at final landing.
- A task or experiment branch rebases exactly once, onto the current base tip, at land time.
- Failed experiments are preserved as branches and worktrees and never merged into the base branch.
- At most one performance optimization experiment is active per expedition at a time, because parallel performance measurements contaminate each other on shared hardware.
- One landing lease per expedition. Tasks and regular experiments merge serially into the base branch even when they run in parallel.
- Parallel expeditions are allowed and only interact through the primary branch.

## Quality Bar

Experiment branches are held to the same production-quality bar as task branches. "Experiment" describes hypothesis uncertainty, not a lower coding standard. No measurement scaffolding, debug prints, stubbed tests, or disabled logging stay behind. A kept experiment merges through the same landing cycle as a task.

## Durable State

The durable expedition files live inside the expedition base branch, not on the
primary branch:

- `docs/expeditions/<expedition>/plan.md`
- `docs/expeditions/<expedition>/log.md`
- `docs/expeditions/<expedition>/handoff.md`
- `docs/expeditions/<expedition>/state.json`

Because multiple expeditions can exist on different branches at the same time,
there is no single tracked repo-root index on the primary branch. Instead,
fresh sessions should discover expeditions by scanning linked worktrees with the
helper below.

## Deterministic Helpers

This skill includes a single CLI at `expedition/scripts/expedition.py` with
the following subcommands:

- `expedition/scripts/expedition.py discover`
  - scan linked worktrees for branch-local expedition state and handoff files
- `expedition/scripts/expedition.py bootstrap --expedition <name> --worktree <path>`
  - preview or create the base branch/worktree plus initial expedition files
- `expedition/scripts/expedition.py start-task --expedition <name> --slug <slug> [--kind task|experiment|perf-experiment]`
  - preview or create the next numbered task or experiment branch/worktree and update expedition state; `perf-experiment` is allowed only if no other perf-experiment is active
- `expedition/scripts/expedition.py verify --expedition <name>`
  - verify that the current checkout matches the expedition base worktree or
    the currently active task worktree
- `expedition/scripts/expedition.py close-task --expedition <name> [--branch <name>] --outcome kept|failed-experiment`
  - for kept branches: acquire the landing lease, rebase the branch onto the current base tip, merge into the base, release the lease; for failed experiments: preserve the branch and release the lease
- `expedition/scripts/expedition.py finish --expedition <name>`
  - verify that the expedition is ready for final landing and remove the
    branch-local expedition files before the last linear merge to the primary branch

Use the helper by script path, not `python3 <script>`, so approvals stay
scoped to the script.

## Session Start Protocol

At the start of every fresh session:

1. Run:

```bash
expedition/scripts/expedition.py discover
```

2. If the user named an expedition, select it.
3. If exactly one expedition is discoverable, use it.
4. If multiple expeditions are discoverable and none was named, ask the user
   which expedition to resume.
5. Read `handoff.md`, then the `RESUME HERE` block in `log.md`, then the last
   1-3 log entries.
6. Verify the current checkout with:

```bash
expedition/scripts/expedition.py verify --expedition <name>
```

Do not ask the user to reconstruct prior context when the expedition handoff
files already exist.

If discover reports stale_active_branches, inspect each listed branch and decide case-by-case whether the teammate's work is recoverable or the entry should be closed out.

## Session End Protocol

Every session should end on the expedition base branch and rewrite
`handoff.md`. A typical cycle is:

1. Create or resume the base worktree.
2. Triage the expedition plan and launch any number of task and regular experiment branches in parallel. Launch at most one performance optimization experiment branch at a time.
3. As each branch completes, close it via close-task to acquire the lease, rebase onto the base tip, and merge.
4. Failed experiment branches are preserved without merge; record the outcome in the log and release the lease.
5. Re-triage and launch replacement branches from the now-advanced base.
6. Update state.json, log.md, and handoff.md (these are written by the coordinator, never by teammates).

## Final Landing

When the last kept task is complete:

1. Merge the final task branch into the base branch.
2. Rebase the base branch onto the primary branch.
3. Run the final expedition verification gates.
4. Remove the expedition-local docs with:

```bash
expedition/scripts/expedition.py finish --expedition <name> --apply
```

5. Commit the expedition-doc removal on the rebased base branch.
6. Land the rebased base branch onto the primary branch using the repo's normal
   landing flow. Use `land-work` when its safety checks are relevant.

## Non-Negotiable Rules

- Only the coordinator writes to docs/expeditions/<expedition>/*. Teammates never commit there.
- Do not launch a second performance optimization experiment for an expedition while one is active.
- Do not rebase task or experiment branches outside the close-task rebase-onto-base step.
- Do not rebase the expedition base branch onto anything except the detected primary branch, and only do so at final landing.
- Do not merge one expedition base branch directly into another expedition base branch.
- Do not delete failed experiment branches before their result is captured in the log.
- Do not rely on a pasted chat prompt when expedition handoff files already exist.
- Do not update expedition state from the primary checkout when the expedition's base worktree is available.

## Templates

Use the reference templates under `expedition/references/templates/` when
you need to inspect or rewrite the human-facing expedition docs manually.
