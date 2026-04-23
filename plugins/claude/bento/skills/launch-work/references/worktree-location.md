# Worktree Location

Shared guidance for linked-worktree placement. Referenced by the `launch-work`
and `expedition` skills.

## Default

When the repo does not document a different root, place linked worktrees at:

    ~/.local/share/worktrees/<repo>/<branch>

This root is the default because it is durable, user-scoped, and outside both
the checkout and common clutter zones.

## Prohibitions

Do not place linked worktrees:

- under `/tmp` unless the repo explicitly documents that as safe and durable
  enough for the task
- directly under the user's home directory
- under the project parent directory
- inside the checked-out repository

unless the repo explicitly documents that convention.

## Overrides

If the repo overrides the root, prefer another dedicated durable worktree
directory — not an ad hoc "nearby" folder.
