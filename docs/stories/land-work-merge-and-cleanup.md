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
An agent finishes implementation on a feature branch, all required checks have passed, and the user signals readiness to land. The land-work skill fires. It first runs the prepare helper to confirm the checkout is a clean feature-branch worktree with commits to land and that it is not stale relative to the primary branch. Before merging, it runs an independent code review of the feature-only diff (computed with `git merge-base` so primary-branch commits merged in during development are excluded), passing the reviewer only the change and a purpose statement drawn from the tracker issue — not the implementation session's reasoning. Critical and Important findings are fixed before the landing proceeds. It rebases the branch onto the current primary-branch base, materializes a preview merge, runs the project verifier against that exact preview, and runs the discovered gate suite against the same candidate — halting rather than landing if the primary base was already red. On success it re-checks the lease and executes the actual merge with an explicit merge commit. After the merge is confirmed on the primary branch, the tracker issue is closed with the gate commands and exit statuses as landing evidence, the preview worktree is cleaned up, the primary checkout root is audited for hygiene, every untracked path is committed, gitignored, or deleted, and finally the feature branch is deleted and the linked worktree removed. The agent ends with a clean primary-branch state and no orphaned worktrees.

## Expected Behavior
- The prepare helper verifies the worktree is clean, on a feature branch, and not stale.
- An independent code review of the feature-only diff runs before merging; Critical and Important findings are fixed first.
- A preview merge is created and verified before the real merge runs.
- The project verifier must exit 0 against the exact merge preview; a verifier selecting zero checks against a real diff is a landing failure, not evidence.
- The gate suite is discovered and run against the candidate, and landing halts if the primary base was already red.
- The merge uses an explicit merge commit (no squash, no fast-forward).
- The tracker issue is closed only after verified landing, not when implementation merely completes, and the closure note carries the gate commands and their exit statuses.
- The preview worktree is cleaned up on every exit path, and no untracked files are left behind before the worktree is removed.
- The feature branch and its linked worktree are deleted after the merge.

## Boundaries
- Does not clean up other agents' branches or worktrees; that is the closure skill's responsibility.
- Does not apply until all required tests, lint, and build checks have passed.
- Does not land silently through a manual conflict resolution: a resolved candidate requires a fresh gate run and an explicit review checkpoint before merging.

## Auditable Claims
- `land-work/scripts/land-work-prepare.py` verifies the current checkout is a clean feature-branch worktree.
- `land-work/scripts/land-work-create-preview.py` materializes the merge candidate before the real merge.
- The SKILL.md hard-trigger description reads: "invoke after finishing your own approved feature-branch work to merge it, close tracker work, and tear down the feature branch and its linked worktree afterward."
- SKILL.md step 4 requires an independent code review of the feature-only diff before merging, using `git merge-base` to compute the diff range and fixing Critical/Important findings first.
- `land-work/scripts/land-work-run-verifier.py` must exit 0 on the exact merge preview before the merge; its contract is `land-work/references/project-verifier.md`.
- Gate discovery, the red-base halt, and the evidence-in-closure-note requirement are documented in `land-work/references/gate-evidence.md`.
- land-work invokes `../launch-work/scripts/run-lifecycle-extensions.py` at the `pre` (blocking) and `post` (advisory) boundaries.
- Tracker issue closure happens only after verified landing and carries gate evidence in the note. The named "Closure Evidence Rule" is defined in the `beads-issue-flow` skill, not land-work; land-work's own rule is documented in `references/workflow-invariants.md`.

## Evidence
### Tests
- `tests/land_work/test_land_work_scripts.py`
- `tests/land_work/test_land_work_verifier.py`
- `tests/land_work/test_land_work_root_hygiene.py`
### Surface
- `skill: land-work`
### Docs
- `catalog/skills/land-work/SKILL.md`
- `catalog/skills/land-work/references/project-verifier.md`
- `catalog/skills/land-work/references/gate-evidence.md`
- `catalog/skills/beads-issue-flow/SKILL.md`
