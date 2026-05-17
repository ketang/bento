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

## Permission Pre-Authorization

The bento `SessionStart` hook `ensure-worktree-permissions.py` adds the default
root above, plus the parent directories of any existing linked worktrees in
the current repo, to `permissions.additionalDirectories` in
`~/.claude/settings.json`. This suppresses the per-file permission prompt for
worktree access in subsequent sessions.

Caveat: settings changes take effect on the next session, not the current
one. The first worktree created under a non-default override path will still
prompt during the session in which it was created; the next session will
self-heal.

## Claude Main-Branch Edit Guard

The bento Claude plugin also installs a `SessionStart` hook that registers a
global `PreToolUse` guard for `Edit`, `Write`, and `NotebookEdit`. The guard
blocks those file-editing tools when the active checkout is a git repository on
the branch named `main`. This is a mechanical backstop for the launch-work
contract: agents should create a linked worktree and edit there instead of
editing the primary checkout directly.

The guard allows these cases:

- the current directory is not in a git repository
- `git branch --show-current` returns empty output, such as detached HEAD
- the current branch is anything other than `main`
- the repository root contains `.agent-mode.local` with
  `require_worktree=false`

The `.agent-mode.local` file is a developer-local opt-out. It is parsed as
one `key=value` pair per line, with `#` comments ignored. If the file is absent
or does not contain `require_worktree=false`, the guard enforces the default.
The hook does not modify `.gitignore`; projects that use the opt-out should
ignore `.agent-mode.local` themselves if they do not want it committed.
