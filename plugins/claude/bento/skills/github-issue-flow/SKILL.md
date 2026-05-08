---
name: github-issue-flow
description: Use when the repo uses GitHub Issues as its tracker — list, claim, and close issues only after verified landing.
recommended_model: low
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

## Pre-Filing Readiness Check

Before `gh issue create`, confirm the draft is workable. At filing time you
hold the symptom and the session that produced it, so ambiguities feel
resolved. A later agent sees only the issue body, and the same ambiguities
block progress. Filing-time and work-time judgments diverge for structural
reasons, not skill reasons.

Use a blank-slate subagent as reviewer. Hand off via local temp files so an
unworkable draft never enters the tracker.

1. Write the proposed title and body to a temp file. Reserve a sibling path
   for the verdict:

   ```bash
   draft=$(mktemp -t issue-draft.XXXXXX.md)
   review=${draft%.md}.review.md
   ```

2. Dispatch a fresh subagent (e.g. `general-purpose`) with a self-contained
   prompt. Do not pass the current chat, repro session, or files you read
   while drafting. Instruct it to read only `$draft` and write its verdict
   to `$review`. The verdict must answer: could I start work right now?
   what is ambiguous, unscoped, or missing (acceptance check, in/out of
   scope, smallest reproducible case, rough size signal)? would I refuse it
   as too big or too vague?

3. Read `$review`. If gaps were flagged, revise the draft and re-review, or
   file the issue with the repo's documented triage label and note the
   unresolved questions in the body. Do not submit a draft that failed
   review without an explicit triage label.

4. Only after the draft passes review (or is explicitly filed for triage)
   run `gh issue create` with the contents of `$draft`.

5. Delete the temp files after submission.

The tracker never receives a draft that has not been through this loop.

## Policy Notes

- Do not assume every repo uses an `in-progress` label.
- Do not assume assignee-based claiming is canonical.
- Do not assume closing always happens on merge to `main`; follow the repo's
  documented primary-branch naming and landing flow.
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
