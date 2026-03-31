# Beads Overlay For Closure

Use this overlay only when the repo uses Beads for task tracking.

## Tracker Commands

- List tasks: `bd list`
- Show task details: `bd show <id>`
- Close stale or completed tasks: `bd close <id>`

## Correlation Guidance

- Cross-reference branch names with Beads IDs when the naming convention makes
  that possible.
- Record Beads status for each correlated branch.
- When the core skill refers to stale tracker tasks, use Beads issues in
  `ready` or `in-progress` state whose work is already present on the primary
  branch.

## Closeout

- When the core skill says to close a tracker task, run `bd close <id>`.
