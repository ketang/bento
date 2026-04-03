---
name: github-issue-flow
description: |
  Use when a repo uses GitHub Issues as its canonical tracker. Covers listing
  and inspecting issues, following the repo's documented active-claim
  mechanism, and closing or updating issues only after verified landing.
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
