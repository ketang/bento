---
name: beads-issue-flow
description: Use when the repo uses Beads as its tracker — read, claim, update, and close issues at the correct landing-lifecycle stage.
recommended_model: low
---

# Beads Issue Flow

## Model Guidance

Recommended model: low.

Use a higher-capability model only when the repo's tracker policy is unclear or
this skill is being combined with higher-risk landing work.

Use this skill only when the project documents Beads as the issue tracker.

## Core Workflow

1. Use `bd` commands to inspect and select work.
2. Determine the repo's documented active-work status before changing issue
   state.
3. If the repo expects issues to be claimed before implementation, update the
   issue to the documented active-work status, often `in_progress`.
4. Treat issues already carrying the documented active-work status as
   unavailable unless the repo documents an override.
5. If the repo does not use Beads claim semantics beyond ready-work discovery,
   record that and continue without inventing extra transitions.
6. Do not close the issue when branch work is merely complete.
7. Close or update the issue only after the verified landing to the repo's
   primary branch succeeds. See "Closure Evidence Rule" below — non-negotiable.
8. If work is abandoned or handed off without landing, clear or adjust the
   active-work status using the repo's documented policy instead of closing the
   issue.
9. When another skill such as `closure` hands off an apparently landed task,
   verify the landing evidence before mutating tracker state.
10. If cleanup evidence shows the task is superseded, abandoned, or only
    partially landed, update or leave the issue open according to repo policy
    instead of closing it.

## Closure Evidence Rule

Never close a Beads issue without proof its branch is reachable from the
integration branch. Closing without landing silently breaks dependents: a
downstream issue marked ready will be claimed and fail on first reference to
unlanded code.

Required before `bd close <id>`:

1. Capture the merge SHA from `land-work` (or `git rev-parse <integration-branch>`
   immediately after the merge).
2. Verify ancestry:

   ```bash
   git merge-base --is-ancestor <merge-sha> <integration-branch>
   ```

   Exit code `0` means landed. Any non-zero exit means refuse to close.
3. Only then run:

   ```bash
   bd close <id> --reason "<merge-sha> landed on <integration-branch>"
   ```

If the ancestry check fails, do not close. Direct the user to land the branch
first. Do not bypass with `bd update <id> --status closed`, and do not close
on cleanup evidence alone. The rule applies even when the closing agent just
ran `land-work` itself — capture the SHA and run the check anyway.

## Policy Notes

- Do not assume every repo uses `in_progress` as the active-work status.
- Do not assume closing always happens on merge to `main`; follow the repo's
  documented primary-branch naming and landing flow.
- Do not invent extra Beads statuses or transitions that the repo does not
  document.
- Do not close from cleanup evidence alone unless the landed-work correlation
  is strong enough to explain and defend.

## Worktree Caveat

If the tracker keeps repository-local state, run Beads commands from the
primary checkout rather than from a linked worktree unless the project
explicitly documents worktree-safe usage. This tracker-state mutation does not
by itself count as implementation work or require a feature branch.

## Common Commands

```bash
bd list
bd ready
bd show <id>
bd create --title "..." --description "..."
bd update <id> --status <status>
bd close <id> --reason "<merge-sha> landed on <integration-branch>"
```

Prefer `bd close --reason` over `bd update <id> --status closed`. The former
records the landing evidence on the issue; the latter loses that audit trail.

### Closure

Three valid closure forms, in order of preference:

1. **Canonical:** `bd close <id> --reason "..."` — purpose-built; `--reason`
   (`-r`) matches the mental model and records landing evidence.
2. **Atomic fallback:** `bd update <id> --status closed --notes "..."` — use
   only when also setting other fields in the same call (e.g.,
   `--add-label`, `--assignee`). On `update`, `--notes` is the only
   message-bearing flag; `--reason`, `-m`, and `--message` do not exist.
3. **Append a note:** `bd note <id> "..."` — shorthand for
   `bd update <id> --append-notes "..."`. No `-m` here either.

Common agent miss: `bd update <id> --status closed --reason "..." -m "..."`
fails — neither `--reason` nor `-m` exists on `update`. Use form 1 instead.

## Dependency Links

When creating a blocks relationship, prefer:

```bash
bd dep <blocker> --blocks <blocked>
```

Use this flag form because it makes the direction explicit at the call site.
Do not use positional `bd link <a> <b>` or `bd dep add <a> <b>` in
agent-authored commands; those forms are easy to invert.

After creating a dependency, always verify it with:

```bash
bd dep list <blocked>
```

Confirm the blocker appears under `blocked by`, not under `blocks`.

Worked example:

- English statement: `bento-auth` must finish before `bento-ui`.
- Command: `bd dep bento-auth --blocks bento-ui`
- Verification: run `bd dep list bento-ui` and confirm `bento-auth` appears in
  the `blocked by` section.
