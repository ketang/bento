---
name: beads-issue-flow
description: Use when the repo uses Beads as its tracker — read, claim, update, and close issues at the correct landing-lifecycle stage.
recommended_model: low
---

# Beads Issue Flow

## Model Guidance

Recommended model: low.

Use a higher-capability model only when the repo's tracker policy is unclear or
this skill is being combined with higher-risk landing work.

Use this skill only when the project documents Beads as the issue tracker.

## Core Workflow

1. Use `bd` commands to inspect and select work.
2. Determine the repo's documented active-work status before changing issue
   state.
3. If the repo expects issues to be claimed before implementation, update the
   issue to the documented active-work status, often `in_progress`.
4. Treat issues already carrying the documented active-work status as
   unavailable unless the repo documents an override.
5. If the repo does not use Beads claim semantics beyond ready-work discovery,
   record that and continue without inventing extra transitions.
6. Do not close the issue when branch work is merely complete.
7. Close or update the issue only after the verified landing to the repo's
   primary branch succeeds.
8. If work is abandoned or handed off without landing, clear or adjust the
   active-work status using the repo's documented policy instead of closing the
   issue.
9. When another skill such as `closure` hands off an apparently landed task,
   verify the landing evidence before mutating tracker state.
10. If cleanup evidence shows the task is superseded, abandoned, or only
    partially landed, update or leave the issue open according to repo policy
    instead of closing it.

## Policy Notes

- Do not assume every repo uses `in_progress` as the active-work status.
- Do not assume closing always happens on merge to `main`; follow the repo's
  documented primary-branch naming and landing flow.
- Do not invent extra Beads statuses or transitions that the repo does not
  document.
- Do not close from cleanup evidence alone unless the landed-work correlation
  is strong enough to explain and defend.

## Worktree Caveat

If the tracker keeps repository-local state, run Beads commands from the
primary checkout rather than from a linked worktree unless the project
explicitly documents worktree-safe usage. This tracker-state mutation does not
by itself count as implementation work or require a feature branch.

## Common Commands

```bash
bd list
bd ready
bd show <id>
bd create --title "..." --description "..."
bd update <id> --status <status>
bd close <id>
```
