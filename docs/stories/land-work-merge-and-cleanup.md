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
An agent finishes implementation on a feature branch, all required checks have passed, and the user signals readiness to land. The land-work skill fires. It first runs the prepare helper to confirm the checkout is a clean feature-branch worktree with commits to land — and, when `--require-up-to-date` is passed, that it is not stale relative to the primary branch. It then discovers the repo's gate suite and confirms the primary branch is already green, halting rather than stacking work on a red base. Next it runs an independent code review of the feature-only diff (computed with `git merge-base` so primary-branch commits merged in during development are excluded), passing the reviewer only the change and a purpose statement drawn from the tracker issue — not the implementation session's reasoning. Critical and Important findings are fixed before the landing proceeds. It rebases the branch onto the current primary-branch base, materializes a preview merge, runs the project verifier against that exact preview, and runs the discovered gate suite against the same candidate. On green — or on a waiver recorded in the tracker before the merge — it re-checks the lease, executes the actual merge with an explicit merge commit, and removes the preview worktree. After the merge is confirmed on the primary branch, the tracker issue is closed with the gate commands and exit statuses as landing evidence, the primary checkout root is audited for hygiene, every untracked path is committed, gitignored, or deleted, and finally the feature branch is deleted and the linked worktree removed. The agent ends with a clean primary-branch state and no orphaned worktrees.

## Expected Behavior
- The prepare helper verifies the worktree is clean and on a feature branch, and checks staleness against the primary branch when `--require-up-to-date` is passed.
- An independent code review of the feature-only diff runs before merging; Critical and Important findings are fixed first.
- A preview merge is created and verified before the real merge runs.
- The project verifier must exit 0 against the exact merge preview; a verifier selecting zero checks against a real diff is a landing failure, not evidence.
- The gate suite is discovered and baselined before the merge work begins, and landing halts if the primary base was already red.
- The gate suite is re-run against the exact merge candidate; the merge proceeds only on green or on a waiver recorded in the tracker issue before the merge.
- The merge uses an explicit merge commit; squash is never used, and fast-forward only if the repo explicitly requires it.
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
- The SKILL.md hard-trigger description reads: "Hard trigger — invoke after finishing your own approved feature-branch work to merge it, close tracker work, and tear down the feature branch and its linked worktree afterward. This is the routine post-merge cleanup path for the agent that did the work; do not use closure for that."
- SKILL.md step 4 requires an independent code review of the feature-only diff before merging, using `git merge-base` to compute the diff range and fixing Critical/Important findings first.
- `land-work/scripts/land-work-run-verifier.py` must exit 0 on the exact merge preview before the merge; its contract is `land-work/references/project-verifier.md`.
- Gate discovery, the red-base halt, the waiver path, and the evidence-in-closure-note requirement are all documented in `land-work/references/gate-evidence.md`; `references/workflow-invariants.md` carries only the tracker-timing and cleanup-ordering rules.
- land-work invokes `../launch-work/scripts/run-lifecycle-extensions.py` at the `pre` (blocking) and `post` (advisory) boundaries.
- Tracker issue closure happens only after verified landing and carries gate evidence in the note. The named "Closure Evidence Rule" is defined in the tracker-flow skills — `beads-issue-flow` and `github-issue-flow` — not in land-work, whose own tracker-timing rule lives in `references/workflow-invariants.md`.

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
- `catalog/skills/github-issue-flow/SKILL.md`
