---
name: launch-work
description: |
  Use when starting implementation for an issue or approved change. Claims the
  issue through the project's tracker workflow, creates a dedicated feature
  branch and worktree, verifies the working location, and bootstraps the
  environment before coding.
---

# Launch Work

Use this skill when the task is moving from planning or issue triage into
implementation.

## Inputs

- The active issue or approved task scope
- The project's documented tracker choice
- The project's documented branch/worktree conventions, if any

## Workflow

1. Read the project's local instructions and confirm the issue is the active
   scope.
2. Determine the issue tracker from project docs.
   - If the project uses Beads, use the `beads-issue-flow` skill.
   - If the project uses GitHub Issues, use the `github-issue-flow` skill.
3. Inspect the issue and claim it before implementation begins.
4. Create exactly one feature branch for that issue.
5. Create exactly one dedicated worktree for that branch.
6. Enter the worktree and verify both location and branch:

```bash
pwd
git branch --show-current
```

7. Confirm implementation will happen in the worktree, not in the primary repo
   checkout.
8. If the project is Node/TypeScript based and the fresh worktree cannot resolve
   dependencies, run the documented package install step before debugging build
   failures.

## Non-Negotiable Rules

- One issue or approved task gets one branch and one worktree.
- Do not repurpose an old branch or worktree for a different issue.
- Do not implement directly on `main`.
- Do not implement in the primary repo checkout if the project expects worktree
  isolation.

## Stop Conditions

Stop and ask or re-plan if:

- The issue scope is ambiguous or contradictory.
- The project does not document which tracker it uses.
- The project requires a branch/worktree convention that you cannot verify.
