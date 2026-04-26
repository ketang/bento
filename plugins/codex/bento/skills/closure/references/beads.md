# Beads Overlay For Closure

Use this overlay only when the repo uses Beads for task tracking.

## Tracker Skill

- Use `beads-issue-flow` for all task-state changes.

## Correlation Guidance

- Cross-reference branch names with Beads IDs when the naming convention makes
  that possible.
- Record Beads status, assignee, and blockers for each correlated branch.
- Treat `bd ready --json` as a computed queue, not a status. For stale tracker
  tasks, inspect open, ready, or active/WIP issues whose work is already on
  primary; use `bd statuses --json` if custom statuses may exist.

## Worktrees And Concurrency

- If tracker state differs by worktree, check `bd where --json` or
  `bd context --json`; modern Beads worktrees may share a canonical database
  through `.beads` redirects.
- Do not triage legacy Beads sync worktrees under `.git/beads-worktrees/` or
  `.git/worktrees/beads-*` as dead-agent implementation worktrees.
- For concurrent agents, prefer `bd update <id> --claim`. Beads hash IDs avoid
  branch ID collisions; server mode is the safe multi-writer mode.

## Closeout

- Present the landing evidence first.
- If the task appears complete and landed, hand off to `beads-issue-flow` with
  a `close` recommendation.
- If the work appears superseded, abandoned, or only partially landed, hand off
  to `beads-issue-flow` with an `update` or `leave open` recommendation instead
  of closing it directly from `closure`.
