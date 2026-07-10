---
schema_version: 1
title: Land Work Merges Branch and Cleans Up
slug: land-work-merge-and-cleanup
status: active
authority: observed
change_resistance: medium
tests_applicable: true
locked_sections:
  - Intent
---

# Land Work Merges Branch and Cleans Up

## Intent
After implementation is complete and verified, land-work merges the feature branch into the primary branch, closes the tracker issue, and removes the branch and its linked worktree.

## Story
An agent finishes implementation on a feature branch, all required checks have passed, and the user signals readiness to land. The land-work skill fires. It first runs the prepare helper to confirm the checkout is a clean feature-branch worktree with commits to land and that it is not stale relative to the primary branch. It then materializes a preview merge from the current primary-branch base, runs any repo-required quality gates against the preview, and — on success — executes the actual merge with an explicit merge commit. After the merge is confirmed on the primary branch, the tracker issue is closed with landing evidence, the feature branch is deleted, and the linked worktree is removed. The agent ends with a clean primary-branch state and no orphaned worktrees.

## Expected Behavior
- The prepare helper verifies the worktree is clean, on a feature branch, and not stale.
- A preview merge is created and verified before the real merge runs.
- The merge uses an explicit merge commit (no squash, no fast-forward).
- The tracker issue is closed only after verified landing, not when implementation merely completes.
- The feature branch and its linked worktree are deleted after the merge.

## Boundaries
- Does not clean up other agents' branches or worktrees; that is the closure skill's responsibility.
- Does not apply until all required tests, lint, and build checks have passed.
- Does not handle conflicts or pre-merge rebases; those must be resolved before invoking land-work.

## Auditable Claims
- `land-work/scripts/land-work-prepare.py` verifies the current checkout is a clean feature-branch worktree.
- `land-work/scripts/land-work-create-preview.py` materializes the merge candidate before the real merge.
- The SKILL.md hard-trigger description reads: "invoke after finishing your own approved feature-branch work to merge it, close tracker work, and tear down the feature branch and its linked worktree afterward."
- Tracker issue closure follows the "Closure Evidence Rule" — non-negotiable per SKILL.md.

## Evidence
### Tests
### Surface
- `skill: land-work`
### Docs
- `catalog/skills/land-work/SKILL.md`
