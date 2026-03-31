---
name: land-work
description: |
  Use when a feature branch is ready to merge. Runs the branch landing flow:
  verify preconditions, rebase onto the latest main, perform a lease-protected
  merge, close the issue only after merge, and clean up branch/worktree state.
---

# Land Work

Use this skill when implementation is complete and the branch is ready to land.

## Preconditions

- The work is committed on the feature branch.
- Required tests, lint, and build checks have passed.
- The project allows command-line merges to `main`.

## Workflow

1. Confirm the branch is the intended landing branch.
2. Re-run or verify the required quality gates for the project.
3. Rebase the branch onto the latest `origin/main`.
4. Push the branch with `--force-with-lease` if rebasing changed history.
5. Prefer the project's documented merge helper if one exists.
6. Otherwise, perform a compare-and-set merge flow:
   - refresh `origin/main`
   - capture the leased `origin/main` SHA
   - create a `--no-commit --no-ff` merge preview
   - run the required verification gate against that exact preview
   - refresh `origin/main` again
   - abort if the lease changed
   - commit and push only if the lease still matches
7. After the merge succeeds, close the issue through the project's tracker
   workflow.
8. Clean up local branch/worktree state using the project's documented process.

## Non-Negotiable Rules

- Do not close the issue before the verified merge succeeds.
- Do not fast-forward feature branches into `main`.
- Do not merge if `origin/main` moved after verification.
- Do not change the repository's configured Git transport just because auth
  fails.

## Tracker Handoff

- If the project uses Beads, use the `beads-issue-flow` skill to close or update
  the issue after merge.
- If the project uses GitHub Issues, use the `github-issue-flow` skill.
