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
repo does not document a different root. Do not place linked worktrees under
`/tmp`, at the top level of the user's home directory, in the project parent,
or inside the checked-out repository unless the project explicitly documents a
different durable location.

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

## Landing Queue

Ready-to-land signals are persisted, not held in the lead's context, at
`$(git rev-parse --git-common-dir)/bento/landing-queue.json` (shared by all
worktrees; not runtime- or session-scoped). Manage it only through
`swarm/scripts/swarm-landing-queue.py`:

- `add <branch> --worktree <path> [--tracker-id ..] [--gate-summary ..]` on
  each ready signal (re-adding a branch replaces its entry)
- `pop <branch>` after it lands (non-zero if not queued)
- `defer <branch> --reason <why>` to stop it blocking Stop (still reported)
- `list` prints entries; `clear --all --yes` is operator-only

Each entry records `lead_agent` `{pid, start_time}` — the nearest `claude`/
`codex` ancestor process — so `check-landing-queue.py` (Stop hook) blocks only
that lead session while non-deferred, unmerged entries remain. A one-turn hold
marker `bento-check-landing-queue-hold-<session_id>` in `$XDG_RUNTIME_DIR` (or
`/tmp`) lets one Stop through. `agent-env-doctor` reports entries older than
1 h whose branch is unmerged as "N ready-but-unlanded branches".
