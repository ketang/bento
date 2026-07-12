---
name: github-issue-flow
description: Use when the repo uses GitHub Issues as its tracker — list, claim, and close issues only after verified landing.
---

# GitHub Issue Flow

## Model Guidance

Recommended model: low.

Use a higher-capability model only when the repo's issue workflow is unclear or
this skill is being combined with higher-risk landing work.

Use this skill only when the project documents GitHub Issues as the canonical
tracker.

## Core Workflow

1. Inspect the relevant issue before implementation begins.
2. Determine the repo's documented active-claim mechanism before touching issue
   state.
3. If the repo uses an active-claim mechanism such as a label, assignee, or
   project field, apply it before implementation begins.
4. Treat issues already carrying the documented active-claim signal as
   unavailable unless the repo documents an override.
5. If the repo does not use claim semantics for GitHub Issues, record that and
   continue without inventing one.
6. Do not close the issue when branch work is merely complete.
7. Close or update the issue only after the verified landing to the repo's
   primary branch succeeds.
8. If work is abandoned or handed off without landing, clear or adjust the
   active-claim signal using the repo's documented policy instead of closing the
   issue.
9. When another skill such as `closure` hands off an apparently landed issue,
   verify the landing evidence before mutating issue state.
10. If cleanup evidence shows the issue is superseded, abandoned, or only
    partially landed, update or leave the issue open according to repo policy
    instead of closing it.

## Closure Evidence Rule

Never close a GitHub issue without proof its branch is reachable from the
integration branch. Closing without landing silently breaks dependents:
downstream work marked ready will be started and fail on first reference to
unlanded code.

Required before `gh issue close <id>`:

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
   LOCAL=$(git rev-parse <integration-branch>)
   REMOTE=$(git ls-remote origin <integration-branch> | cut -f1)
   [ "$LOCAL" = "$REMOTE" ] && echo OK || echo BEHIND
   ```

   `git ls-remote` prints `<sha>\t<refname>`; `cut -f1` takes the SHA field.
   The push is confirmed only when the two values match exactly. If the remote
   SHA differs or `git ls-remote` returns nothing for the branch, the landing
   is not yet published — refuse to close until the integration branch is pushed.
4. Only then run `gh issue close <id>`.

If the ancestry check fails, do not close. Direct the user to land the branch
first. Do not close on cleanup evidence alone. The rule applies even when the
closing agent just ran `land-work` itself — capture the SHA and run both the
ancestry and the push checks anyway.

Pushing the integration branch is `land-work`'s responsibility; this rule does
not push on its behalf. It only refuses to close until that push is confirmed,
so a landed-but-unpushed branch cannot be marked done.

## Filing New Issues

Before `gh issue create`, use the `issue-readiness-check` skill on the
proposed title and body. Only create the GitHub issue after the shared
precheck returns `ready: yes`, or `ready: triage-only` with the repo's
documented triage label and unresolved questions included in the body.

## Migrating to/from this tracker

When moving a repo onto GitHub Issues from another tracker (or off it), follow
`references/tracker-migration.md`. It covers migrating open issues with a
count reconciliation, archiving the old tracker's state deliberately, and
cleaning up stale tracker-specific `.gitignore` entries.

## Policy Notes

- Do not assume every repo uses an `in-progress` label.
- Do not assume assignee-based claiming is canonical.
- Do not assume closing always happens on merge to `main`; follow the repo's
  documented primary-branch naming and landing flow.
- Keep issues reasonably self-contained. Prefer putting the necessary context in
  the issue itself instead of pointing to external files.
- Avoid references to local filesystem paths or other access-scoped artifacts
  unless there is no practical alternative, such as an image hosted in a
  tracker that cannot take attachments.
- Do not invent extra labels, comments, or issue transitions that the repo does
  not document.
- Do not close from cleanup evidence alone unless the landed-work correlation
  is strong enough to explain and defend.

## Common Commands

```bash
gh issue list
gh issue view <id>
gh issue create --title "..." --body "..."
gh issue edit <id> --add-label <label>
gh issue edit <id> --remove-label <label>
gh issue edit <id> --add-assignee <user>
gh issue edit <id> --remove-assignee <user>
gh issue close <id>
```
