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

### Epic Filtering in Work Discovery

Never claim or start an `issue_type=epic` from `bd ready` as ordinary
implementation work. Epics are containers for child issues, not actionable tasks.

When selecting work from `bd ready`:

1. Prefer `bd ready --json` for programmatic selection. Filter out any item
   where `issue_type` equals `epic` before choosing work.
2. Do not rely solely on `bd ready --exclude-type=epic` — that flag may not
   exist in all Beads versions. Always apply your own filtering as the primary
   mechanism.
3. If `bd ready` returns only epics (no non-epic issues):
   - Run `bd epic status` to inspect open epics.
   - For each relevant epic, run `bd children <epic-id>` to list its children.
   - If all non-epic children are blocked, claimed, deferred, or closed, report
     that there is no actionable ready work. Do not fabricate tasks.
   - If actionable children exist but are not yet marked ready, report that and
     let the user or dependency resolution advance them.
4. Do not mark epics `blocked` or `deferred` merely to hide them from
   `bd ready`. Those states have semantic meaning; applying them to suppress
   display corrupts the dependency graph.

Parent-child links remain organizational, not sequencing dependencies. An epic
appearing in `bd ready` does not imply its children are ready or that the epic
itself is workable.

## Filing New Issues

Before `bd create`, use the `issue-readiness-check` skill on the
proposed title and description. Only create the Beads issue after the shared
precheck returns `ready: yes`, or `ready: triage-only` with the repo's
documented triage marker and unresolved questions included in the description.

### Epics

Use an epic only as a container for related child work, not as a standalone
implementation task. If a request is too broad for one normal issue, create an
epic plus concrete child issues instead of filing one oversized issue.

Create the epic first:

```bash
bd create --type epic --title "..." --description "..."
```

Then create each child with an explicit parent:

```bash
bd create --type task --parent <epic-id> --title "..." --description "..."
```

Use the child issue types that match the work (`task`, `bug`, `feature`, etc.).
Do not rely on title wording, labels, or notes to imply epic membership.

Parent-child membership is not a sequencing dependency. If one child must land
before another child can start, add a normal blocking edge between the children
as described in "Dependency Links" below.

After creating or changing an epic, verify the structure:

```bash
bd children <epic-id>
bd epic status
```

Confirm every intended child appears under the epic. For any ordered child work,
also verify the explicit `blocks` edges with `bd dep list`.

Do not manually close an epic while it still has open children. Beads
auto-closes an epic when the last open child is closed through normal `bd close`
behavior. If an older or interrupted workflow leaves completed epics open, run:

```bash
bd epic close-eligible
```

Use `bd epic close-eligible --dry-run` first when auditing several epics.

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
3. Verify the integration branch is pushed, not just landed locally. A local
   merge that never reaches the remote leaves dependents broken for everyone
   else: they pull an integration branch that lacks the landed code. Compare
   the local tip against the remote tip directly rather than trusting tracking
   refs, which can be stale:

   ```bash
   git rev-parse <integration-branch>
   git ls-remote origin <integration-branch>
   ```

   The two SHAs must match. If the remote is behind (or `git ls-remote`
   returns nothing for the branch), the landing is not yet published — refuse
   to close until the integration branch is pushed.
4. Only then run:

   ```bash
   bd close <id> --reason "<merge-sha> landed on <integration-branch>"
   ```

If the ancestry check fails, do not close. Direct the user to land the branch
first. Do not bypass with `bd update <id> --status closed`, and do not close
on cleanup evidence alone. The rule applies even when the closing agent just
ran `land-work` itself — capture the SHA and run both the ancestry and the
push checks anyway.

Pushing the integration branch is `land-work`'s responsibility; this rule does
not push on its behalf. It only refuses to close until that push is confirmed,
so a landed-but-unpushed branch cannot be marked done.

## Policy Notes

- Do not assume every repo uses `in_progress` as the active-work status.
- Do not assume closing always happens on merge to `main`; follow the repo's
  documented primary-branch naming and landing flow.
- Keep issues reasonably self-contained. Prefer putting the necessary context in
  the issue itself instead of pointing to external files.
- Avoid references to local filesystem paths or other access-scoped artifacts
  unless there is no practical alternative, such as an image hosted in a
  tracker that cannot take attachments.
- Do not invent extra Beads statuses or transitions that the repo does not
  document.
- Do not close from cleanup evidence alone unless the landed-work correlation
  is strong enough to explain and defend.

## Precedence Over Session-Completion Blocks

Some repos carry a bd-generated session-completion block in their agent docs
("Work is NOT complete until `git push` succeeds", with a MANDATORY push step).
That block is about not stranding committed work on a local machine; it is not
a landing policy. Where the two overlap, this skill's landing-lifecycle rules
take precedence:

- "Push" in that block applies to tracker-sync commits (e.g. the Beads export
  and `refs/dolt/data`) and to integration branches that have already been
  landed through the repo's documented merge flow.
- It is never license to commit code directly to the primary branch, or to
  push a feature branch as a substitute for landing it. Code reaches the
  primary branch only through `land-work` (or the repo's documented landing
  path), and the issue closes only after the Closure Evidence Rule above —
  ancestry plus the published-push check — passes.
- A push that has not gone through the landing flow does not satisfy the
  Closure Evidence Rule and does not authorize `bd close`.

When the session-completion block says "push" and this skill says "do not
close until landed and pushed," follow this skill: push the tracker state and
any already-landed branch, and withhold closure until landing is verified.

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
bd create --type epic --title "..." --description "..."
bd create --type task --parent <epic-id> --title "..." --description "..."
bd update <id> --status <status>
bd close <id> --reason "<merge-sha> landed on <integration-branch>"
bd children <epic-id>
bd epic status
bd epic close-eligible
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
bd dep list <blocker> --direction=up
```

Confirm the first command shows the blocker as something `<blocked>` depends
on, and the second command shows `<blocked>` as a dependent of `<blocker>`.
If the relationship points the other way, remove it and recreate it with the
explicit `--blocks` form.

Worked example:

- English statement: `bento-auth` must finish before `bento-ui`.
- Command: `bd dep bento-auth --blocks bento-ui`
- Verification: run `bd dep list bento-ui` and confirm `bento-auth` is a
  dependency; run `bd dep list bento-auth --direction=up` and confirm
  `bento-ui` is a dependent.
