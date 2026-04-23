# Worktree Liveness Triage

For each linked worktree, assess liveness and value before taking any action.

A worktree is **live** only if there is affirmative evidence: a running
process holding the worktree as its CWD (`confirmed_live`), or recent activity
combined with an open session log (`possibly_live`). Uncommitted working-tree
changes are **not** affirmative evidence of liveness — a crashed machine, a
failed run, or an agent that wrote files and then died all leave dirty trees.

## Decision Tree

- `confirmed_live` → do not touch; note the worktree is actively in use.
- `possibly_live` or `recently_active` → present the liveness signals to the
  user and ask before taking any action; the agent may be waiting for input.
- `stale` or `unknown` with a `merged_checked_out` branch → the useful work is
  already in primary; recommend removing the worktree. If the worktree is also
  clean, the helper apply mode may remove that linked worktree and then delete
  the merged branch. This order matches
  `../../land-work/references/workflow-invariants.md` and avoids detached
  `HEAD` orphans.
- `stale` or `unknown` with an unmerged branch → investigate commits and diff
  vs. primary; classify as `incomplete but valuable`, `superseded`,
  `conflicted`, or `unknown`; recommend `land-work` if appropriate.
- Dirty working tree in a stale/unknown worktree → summarize the uncommitted
  changes (file list, rough diff size) so the user can judge salvage value; do
  not discard without presenting the evidence.
