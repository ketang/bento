# Beads Overlay For Closure

Use this overlay only when the repo uses Beads for task tracking.

## Tracker Skill

- Use `beads-issue-flow` for all task-state changes.

## Correlation Guidance

- Cross-reference branch names with Beads IDs when the naming convention makes
  that possible.
- Record Beads status for each correlated branch.
- When the core skill refers to stale tracker tasks, use Beads issues in
  `ready` or `in-progress` state whose work is already present on the primary
  branch.

## Closeout

- Present the landing evidence first.
- If the task appears complete and landed, hand off to `beads-issue-flow` with
  a `close` recommendation.
- If the work appears superseded, abandoned, or only partially landed, hand off
  to `beads-issue-flow` with an `update` or `leave open` recommendation instead
  of closing it directly from `closure`.
