# Swarm Continuation State

When a batch overflows the current run, persist the remaining task IDs in
runtime-local continuation state so a later invocation can resume the same task
set without re-querying the tracker.

## Session ID Pre-Flight (Claude Code only)

Swarm continuation state requires a stable session identifier. In Claude Code,
this is provided by the `session-id@bento` plugin, which installs a
`SessionStart` hook that writes the active session ID to `~/.claude/session_id`.

Before proceeding with triage, verify the hook is active:

1. Read `~/.claude/settings.json` and check whether `enabledPlugins` contains
   `"session-id@bento": true`.
2. If the entry is missing or set to `false`, add or update it to `true` and
   write the file back.
3. After enabling, inform the user that the hook will take effect on the next
   session start (or `/reset`), and that the current session can fall back to
   inferring the session ID from the active JSONL log path under
   `~/.claude/projects/`.

Skip this check when running under Codex (which exposes `CODEX_THREAD_ID`
natively).

## State Roots

Use runtime-scoped state rooted at:

- `.agent-state/swarm/claude/<session-id>/` in Claude Code, where the session
  ID is read from `~/.claude/session_id` (written by the `session-id@bento`
  hook) or, if that file is missing or stale, inferred from the basename of
  the most recently modified JSONL file under
  `~/.claude/projects/<encoded-path>/`
- `.agent-state/swarm/codex/$CODEX_THREAD_ID/` in Codex
- `.agent-state/swarm/<runtime>/<session-or-thread-id>/` at repo root when a
  runtime-specific helper needs a stable fallback path inside the checkout

These state roots are for ephemeral continuation data, not for linked
worktrees. Worktree creation should follow the project's shared worktree
convention, defaulting to `~/.local/share/worktrees/<repo>/<branch>` when the
repo does not document a different root.

## File Formats

Inside that state root, keep the files minimal and role-specific:

- `continue.txt` for remaining task IDs only
- `handoff.md` for the compact narrative needed after a context reset

Keep `continue.txt` tracker-agnostic:

- one task ID per non-empty line
- ignore blank lines and lines beginning with `#`
- do not store tracker metadata, priorities, or prose
- do not share one runtime's continuation state with another runtime unless the
  handoff is intentional
- if explicit task IDs are supplied on a later invocation, they supersede the
  continuation state for the current runtime
- once `continue.txt` has been fully consumed, delete it for the current
  runtime

Keep `handoff.md` short and reset-oriented:

- record only the last landed or deferred task plus what the next invocation
  needs to know
- include branch, worktree, verification, and any newly unblocked follow-up
  tasks when relevant
- treat this state as ephemeral; if the runtime-local directory disappears,
  recompute from tracker and repo state rather than treating it as a fatal error
