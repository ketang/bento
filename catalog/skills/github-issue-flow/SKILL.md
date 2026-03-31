---
name: github-issue-flow
description: |
  Use when a project uses GitHub Issues as its tracker. Covers listing and
  inspecting issues, claiming work with an in-progress label, and closing issues
  only after a verified merge.
---

# GitHub Issue Flow

Use this skill only when the project documents GitHub Issues as the canonical
tracker.

## Core Workflow

1. Inspect the relevant issue before implementation begins.
2. Claim the issue by applying the `in-progress` label unless the project
   documents a different canonical mechanism.
3. Treat issues already carrying the active-claim label as unavailable.
4. Prefer the dedicated `in-progress` label over assignee-based claiming unless
   the project says otherwise.
5. Do not close the issue when branch work is merely complete.
6. Close the issue only after the verified merge to `main` succeeds.

## Common Commands

```bash
gh issue list
gh issue view <id>
gh issue create --title "..." --body "..."
gh issue edit <id> --add-label in-progress
gh issue edit <id> --remove-label in-progress
gh issue close <id>
```
