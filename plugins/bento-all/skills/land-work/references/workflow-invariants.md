# Cross-Skill Workflow Invariants

Use this reference when `land-work` and `closure` need the same git or tracker
invariant without duplicating the rationale.

## Primary Branch Terminology

- "Primary branch" means the repo's detected integration branch.
- Do not assume the primary branch is named `main`.
- When a skill or helper can detect the primary branch from repo state, use
  that detected branch in instructions and decisions.

## Tracker Mutation Timing

- Close or update tracker items only after the underlying work is verified as
  landed on the primary branch.
- Do not treat "merge was attempted" or "branch looks complete" as sufficient
  evidence for tracker mutation.
- If one skill gathers landing evidence and another skill owns the tracker
  mutation, hand off the evidence instead of duplicating the tracker procedure.

## Linked Worktree Cleanup Order

- When a merged feature branch is still checked out in a linked worktree,
  remove the linked worktree before deleting the branch.
- Deleting the branch first can leave the linked worktree in detached `HEAD`
  state.
- If cleanup stops after the worktree is removed but before the branch is
  deleted, the remaining branch is still a normal merged-branch cleanup case.
