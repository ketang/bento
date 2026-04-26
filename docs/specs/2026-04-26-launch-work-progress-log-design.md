# Launch-Work Progress Log — Design

## Problem

When a `launch-work` agent crashes mid-task — process killed, OS reboot,
terminal closed — the in-flight state lives only in the agent's
conversation. A fresh agent in the same worktree has no breadcrumb back
to the work in progress, so the user has to either rebuild context by
hand or abandon partial work.

The existing `handoff` skill is user-initiated, one-shot, and writes to
`/tmp/`, which does not survive reboot. The `expedition` skill keeps
durable branch-local plan/log/handoff files, but only fits long-lived
multi-task work. Neither covers the per-task crash-recovery case.

## Goals

- A fresh agent in the same worktree can resume a crashed
  `launch-work` task with no input from the user beyond "continue the
  work."
- The recovery breadcrumb is on disk, in the worktree, and survives
  reboot.
- The cleanup story is owned end-to-end by `land-work` so the
  breadcrumb does not leak into the primary branch.

## Non-Goals

- Cross-machine recovery. State lives in the worktree; the worktree is
  on one machine.
- Long-idle resumption (weeks later). Use `expedition` for that.
- Replacing `/handoff`. That stays user-initiated and one-shot.
- Multi-task coordination. One log per branch.

## Solution Overview

Add a tracked, branch-local progress log at `.launch-work/log.md`,
maintained by the working agent on a hybrid checkpoint+discretionary
cadence and removed by `land-work` before the final merge. Closure and
land-work both become log-aware. A fresh agent reads the log and
resumes from the recorded checkpoint.

## Log File

### Location

- Path: `.launch-work/log.md` at the repo root of the worktree.
- Tracked in git.
- One file per worktree. The branch name is implicit (a worktree is
  attached to one branch).
- The hidden `.launch-work/` directory makes it visually clear in
  `git status` that the file is process state, not a deliverable, and
  leaves room for sibling files later (e.g., a future
  machine-readable `state.json`) without scattering dotfiles at the
  repo root.

### Lifecycle

- **Created** by `launch-work` immediately after
  `launch-work-verify.py` succeeds.
- **Updated** by the agent at every mandatory checkpoint and at every
  discretionary trigger (see Cadence).
- **Removed** by `land-work` in a single deletion commit before the
  final merge.

### Structure

The body uses the `handoff` skill's seven-slot template:

1. **Next action** — single concrete next step.
2. **Original task** — user's original request, one line.
3. **Branch & worktree** — current branch, worktree path, primary
   branch.
4. **Verification state** — what ran, what passed, what failed, what
   is untested.
5. **Decisions & dead-ends** — non-obvious choices, ruled-out
   approaches with reasons.
6. **Pending decisions / blockers** — open questions, external
   blockers.
7. **Notes** — free-form prose that does not fit a slot.

A machine-checkable header sits at the top of the file:

```
<!-- launch-work-log
last-updated: 2026-04-26T14:32:11Z
checkpoint: tests-green
-->
```

### Checkpoint Vocabulary

The `checkpoint` field uses a fixed enum mapped to the existing
`launch-work` workflow:

| Checkpoint | Set when |
|---|---|
| `claimed` | Tracker claim succeeded (or no tracker, immediately after launch) |
| `worktree-ready` | `launch-work-verify.py` passes; initial log creation |
| `deps-installed` | Bootstrap command completed |
| `red-test-written` | Failing test committed |
| `tests-green` | Implementation makes the red test pass |
| `verification-passed` | Repo verification gates pass |
| `ready-to-land` | Final state before invoking `land-work` |

A recovery agent uses the checkpoint to pick up at the next workflow
step without re-running prior steps.

## Cadence

### Mandatory Checkpoint Writes

Every transition between checkpoints triggers a log rewrite and a
commit. The agent must not proceed past a checkpoint until the log is
written and committed.

### Discretionary Writes

In addition, the agent rewrites the log when:

- A non-obvious decision is made (slot 5).
- An approach is ruled out (slot 5, with reason).
- A blocker appears or is resolved (slot 6).
- The "Next action" would now be wrong if read by a recovery agent.

### What "Update" Means

The agent always rewrites the entire file. Slots represent current
state, not history; git history is the audit trail.

### Commit Message Format

- Checkpoint write: `chore(launch-work-log): <checkpoint>`
- Discretionary write: `chore(launch-work-log): <short reason>`

The fixed `chore(launch-work-log):` prefix lets `land-work`'s rebase
pass identify log-only commits unambiguously.

### What to Skip

Trivial mid-step state — every test run, every file edited, every
TodoWrite tick. The log is for recovery, not telemetry.

## Resume Protocol

When any agent enters a worktree containing `.launch-work/log.md`:

1. **Read the log first.** Before any other action.
2. **Verify checkout matches.** Run `launch-work-verify.py` against
   the branch and worktree recorded in slot 3. On mismatch, stop and
   surface the mismatch.
3. **Check freshness.** If `last-updated` is older than the system
   boot time (e.g., `uptime -s` on Linux), warn that the previous
   agent likely crashed before its last action completed and the
   "Next action" slot may be stale by one step.
4. **Resume from the recorded checkpoint.** Pick up at the next
   workflow step.
5. **Do not** re-claim, re-create the worktree, or re-install deps —
   the log says these are done.

### Discovery

A fresh agent gets pointed at an in-flight log via two paths:

- **User-driven (primary).** The user starts a fresh session and says
  "the previous agent crashed, continue the work." The agent runs
  `launch-work-discover.py`, surfaces the in-flight worktrees, and
  asks which to resume.
- **Self-discovered (secondary).** When `launch-work` is invoked and
  the proposed branch/worktree already exists with a log file, the
  invocation is treated as a resume request, not a fresh launch.
- **Closure-driven (tertiary).** `closure` surfaces in-flight logs
  during its scan and offers "resume in-flight launch-work" as a
  next-step option (see Closure Integration).

## Helpers

### `launch-work/scripts/launch-work-log.py`

Subcommands:

- `init` — writes the initial log file from the seven-slot template
  at `.launch-work/log.md`. Populates the branch/worktree slot from
  `git rev-parse` and `git worktree list`. Sets
  `checkpoint: worktree-ready` and `last-updated`. Commits with
  `chore(launch-work-log): worktree-ready`.
- `update --checkpoint <name> [--slot <n> --content -]` — rewrites
  the header, optionally updates a single slot from stdin, commits
  with `chore(launch-work-log): <checkpoint>`.
- `read` — emits the parsed header as JSON. Used by `closure-scan`
  and the resume protocol.

The agent fills slot bodies (only the agent has the prose). The
helper handles header maintenance and commits so commit-message
format stays canonical, since `land-work` depends on it.

### `launch-work/scripts/launch-work-discover.py`

Scans linked worktrees for `.launch-work/log.md` files. Emits one
record per discovered log with branch, path, checkpoint, and
last-updated. Used by the user-driven resume path and callable
directly when the user asks "what's in flight?".

## Closure Integration

### Scanner Change

`closure-scan.py` reads `.launch-work/log.md` when present and emits
a per-worktree field:

```json
"launch_work": {
  "present": true,
  "last_updated": "2026-04-26T14:32:11Z",
  "checkpoint": "tests-green"
}
```

When the file is missing, the field is omitted entirely. Consumers
should treat key-absent as "no log present" rather than relying on a
boolean.

### Triage Rule

If `launch_work.present` is true AND `checkpoint != "ready-to-land"`,
the worktree is **never** eligible for automatic deletion under
`--apply delete-local-merged-branches`, even when the liveness
verdict is `stale` or `unknown`. The log is affirmative evidence of
in-flight work — unlike uncommitted state.

### New Recommendation

Closure's next-step menu gains **"resume in-flight launch-work"**,
pointing the user at worktrees with incomplete logs. The
recommendation taxonomy
(`closure/references/recommendation-taxonomy.md`) gains a
`launch_work_in_flight` label.

### New Liveness Signal

The log's `last_updated` timestamp joins HEAD-commit-time and
tracked-file mtime as an input to
`active_seconds_since_activity`.

### Anomaly: ready-to-land on a Merged Branch

A `ready-to-land` log on a merged branch means `land-work` did not
finish its cleanup pass — the deletion commit is missing. Closure
surfaces this as an anomaly worth showing the user, not as a silent
abandon.

## Land-Work Integration

### Pre-Merge Cleanup Phase

Before the existing rebase-onto-primary and merge steps, `land-work`
runs:

1. **Verify `ready-to-land`.** If `.launch-work/log.md` exists but
   `checkpoint != "ready-to-land"`, stop and ask the user — the
   work is not actually ready, or the agent forgot to update the log.
2. **Identify log-only commits.** Walk `<base>..HEAD` and classify
   each commit: log-only (every changed path equals
   `.launch-work/log.md`) vs. work commit.
3. **Drop log-only commits via non-interactive rebase.** Run
   `git rebase -i <base>` with `GIT_SEQUENCE_EDITOR` set to a small
   script that rewrites `pick` → `drop` for each log-only sha. If the
   rebase reports conflicts (a non-log commit also touched the log
   file), abort the rebase and fall through to the fallback.
4. **Commit the deletion.**
   `git rm .launch-work/log.md && git commit -m "chore(launch-work-log): remove"`.
5. **Then proceed** with the existing rebase-onto-primary and merge.

### Fallback Flag

`land-work --keep-log-commits` skips step 3 entirely. Log-only commits
remain in history; step 4 still runs. Reasons: rebase conflicts, or
the user just does not want a rewrite. This is the explicit "accept
the clutter" path.

### Helper

`land-work/scripts/land-work-clean-log.py --base <ref> [--keep-commits]`
performs steps 2–4 in isolation, dry-run by default, with `--apply` to
execute. `land-work` calls it via `--apply`. Same pattern as the
existing `launch-work` helpers.

### Backward Compatibility

If `.launch-work/log.md` does not exist (branch was created without
`launch-work`, or pre-existing branches), the cleanup phase is a
no-op. `land-work` proceeds normally.

### Stop Conditions

Added to `land-work`'s existing stop list:

- Log present but `checkpoint != "ready-to-land"`.
- Rebase conflict during log-commit removal and `--keep-log-commits`
  not specified.

## Launch-Work Workflow Changes

The existing 12-step workflow stays. Insertions:

- **Pre-step (before step 5).** Run `launch-work-discover.py`. The
  invocation is treated as a resume rather than a fresh launch when
  any of these is true: the proposed branch name matches a worktree
  with a log file; the user explicitly named a task that matches an
  in-flight log's "Original task" slot; or the user invoked
  `launch-work` with a `--resume` argument. Otherwise, proceed with a
  fresh bootstrap.
- **After step 8 (`launch-work-verify.py` passes).** Run
  `launch-work-log.py init`. Initial checkpoint is `worktree-ready`.
- **Checkpoint writes folded into existing steps:**
  - Step 4 (claim) → `claimed`
  - Step 8 (verify) → `worktree-ready` (initial log creation)
  - Step 11 (deps installed) → `deps-installed`
  - Step 10 first half (red test written) → `red-test-written`
  - Step 10 second half (tests pass) → `tests-green`
  - Implicit final gate before handoff to `land-work` →
    `verification-passed`, then `ready-to-land`

## Relationship to /handoff

Independent. `/handoff` keeps writing one-shot reboot prompts to
`/tmp/`. The launch-work log is durable on-disk state that survives
reboot. They share the seven-slot template. A user who runs
`/handoff` mid-task gets a chat-pasteable snapshot; the on-disk log
is the crash-recovery source of truth. No code coupling.

## Non-Negotiable Rules (added to launch-work)

- Never proceed past a checkpoint without writing the log first.
- Always rewrite the whole file; never append.
- Never edit the log file directly during checkpoint writes — use
  the helper so commit-message format stays canonical.
  `land-work`'s rebase pass depends on it.

## Open Questions

None at design-approval time. The implementation plan will resolve
finer-grained questions (e.g., exact JSON shape for
`launch-work-discover.py`, exact rebase-conflict detection in
`land-work-clean-log.py`).
