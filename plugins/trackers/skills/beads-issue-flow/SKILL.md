---
name: beads-issue-flow
description: |
  Use when a project uses Beads as its issue tracker. Covers reading issues,
  finding ready work, claiming with in_progress, and closing or updating issues
  at the correct stage of the branch lifecycle.
---

# Beads Issue Flow

Use this skill only when the project documents Beads as the issue tracker.

## Core Workflow

1. Use `bd` commands to inspect and select work.
2. Claim the issue by setting status to `in_progress` before implementation
   begins.
3. Treat issues already marked `in_progress` as unavailable unless the project
   documents an override.
4. Do not close the issue when branch work is merely complete.
5. Close the issue only after the verified merge to `main` succeeds.
6. If work is abandoned or handed off without merge, update the claim instead of
   closing the issue.

## Worktree Caveat

If the tracker keeps repository-local state, run Beads commands from the main
repository checkout rather than from a worktree unless the project explicitly
documents worktree-safe usage.

## Common Commands

```bash
bd list
bd ready
bd show <id>
bd create --title "..." --description "..."
bd update <id> --status in_progress
bd close <id>
```
