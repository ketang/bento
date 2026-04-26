# Closure Recommendation Taxonomy

When the evidence for a branch, worktree, or tracker item is ambiguous,
summarize the situation with a compact recommendation label:

- `duplicate`: another branch or item clearly covers the same work
- `superseded`: a newer branch or change makes this obsolete
- `incomplete but valuable`: worth finishing or handing off to `land-work`
- `conflicted`: likely valuable, but currently blocked by merge or state
  conflicts
- `unknown`: evidence is insufficient for a stronger recommendation
- `launch_work_in_flight`: the linked worktree contains `.launch-work/log.md`
  with `checkpoint != "ready-to-land"`. Mid-task or crashed mid-task; do not
  delete. Surface the worktree path, branch, and checkpoint to the user and
  offer "resume in-flight launch-work."

Treat these labels as review guidance only. The helper output still determines
what is safe to delete — never apply a destructive action on the basis of a
label alone.
