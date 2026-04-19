---
name: expedition-work
description: Use when a large body of mostly interdependent work should run as a named expedition on its own long-lived base branch, with one meaningful task branch at a time, durable in-branch plan/log/handoff files, and preserved failed experiments.
recommended_model: high
---

# Expedition Work

## Model Guidance

Recommended model: high.

Use a high-capability model because this skill coordinates long-lived git
state, branch-local durable notes, and repeated handoffs across fresh agent
sessions.

Use this skill when the user wants an "expedition" rather than a one-off task:

- one named base branch created from the primary branch
- serial task branches created from that base branch
- occasional failed experiments that must be preserved but not merged
- a stronger session-handoff protocol than ad hoc pasted prompts

## Inputs

- The expedition name
- The primary goal and success criteria
- The intended task decomposition, or enough context to write one
- The repo's primary branch, if it differs from the detected default
- The repo's verification gates

## Workflow Model

An expedition is a long-lived serial program of work:

- Base branch: `<expedition>`
- Base worktree: one dedicated linked worktree for that branch
- Task branch: `<expedition>-<nn>-<slug>`
- Experiment branch: `<expedition>-exp-<nn>-<slug>`

Hard invariants:

- Only the base branch rebases.
- The base branch rebases only onto the detected primary branch.
- Task and experiment branches never rebase.
- Only one active task or experiment branch may exist for an expedition at a time.
- A new task branch cannot be created until the previous kept task is merged into
  the base branch and the base branch has rebased onto the primary branch.
- Failed experiments are preserved as branches and worktrees, but never merged
  into the base branch.
- Parallel expeditions are allowed, but expeditions only interact through the
  primary branch after one expedition lands.

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

This skill includes helper scripts under `expedition-work/scripts/`:

- `expedition-work/scripts/expedition-discover.py`
  - scan linked worktrees for branch-local expedition state and handoff files
- `expedition-work/scripts/expedition-bootstrap.py --expedition <name> --worktree <path>`
  - preview or create the base branch/worktree plus initial expedition files
- `expedition-work/scripts/expedition-start-task.py --expedition <name> --slug <slug>`
  - preview or create the next serial task or experiment branch/worktree and
    update the expedition state
- `expedition-work/scripts/expedition-verify.py --expedition <name>`
  - verify that the current checkout matches the expedition base worktree or
    the currently active task worktree
- `expedition-work/scripts/expedition-close-task.py --expedition <name> --outcome kept|failed-experiment`
  - merge a kept task into the base branch, rebase the base onto the primary
    branch, or preserve a failed experiment and update the expedition state
- `expedition-work/scripts/expedition-finish.py --expedition <name>`
  - verify that the expedition is ready for final landing and remove the
    branch-local expedition files before the last linear merge to the primary branch

Use the helpers by script path, not `python3 <script>`, so approvals stay
scoped to the script.

## Session Start Protocol

At the start of every fresh session:

1. Run:

```bash
expedition-work/scripts/expedition-discover.py
```

2. If the user named an expedition, select it.
3. If exactly one expedition is discoverable, use it.
4. If multiple expeditions are discoverable and none was named, ask the user
   which expedition to resume.
5. Read `handoff.md`, then the `RESUME HERE` block in `log.md`, then the last
   1-3 log entries.
6. Verify the current checkout with:

```bash
expedition-work/scripts/expedition-verify.py --expedition <name>
```

Do not ask the user to reconstruct prior context when the expedition handoff
files already exist.

## Session End Protocol

Every session should end on the expedition base branch and rewrite
`handoff.md`. A typical serial cycle is:

1. Create or resume the base worktree.
2. Start exactly one task or experiment branch.
3. Complete the task.
4. If the task is kept, merge it into the base branch and rebase the base
   branch onto the primary branch.
5. If the task is a failed experiment, preserve the branch and worktree, but do
   not merge it.
6. Update `state.json`, `log.md`, and `handoff.md`.

## Final Landing

When the last kept task is complete:

1. Merge the final task branch into the base branch.
2. Rebase the base branch onto the primary branch.
3. Run the final expedition verification gates.
4. Remove the expedition-local docs with:

```bash
expedition-work/scripts/expedition-finish.py --expedition <name> --apply
```

5. Commit the expedition-doc removal on the rebased base branch.
6. Land the rebased base branch onto the primary branch using the repo's normal
   landing flow. Use `land-work` when its safety checks are relevant.

## Non-Negotiable Rules

- Do not create a new expedition task branch while an active task branch still
  exists for that expedition.
- Do not rebase task or experiment branches.
- Do not rebase the expedition base branch onto anything except the detected
  primary branch.
- Do not merge one expedition base branch directly into another expedition base
  branch.
- Do not delete failed experiment branches before their result is captured in
  the expedition log.
- Do not rely on a pasted chat prompt when the expedition handoff files already
  exist.
- Do not update expedition state from the primary checkout when the expedition's
  base worktree is available.

## Templates

Use the reference templates under `expedition-work/references/templates/` when
you need to inspect or rewrite the human-facing expedition docs manually.
