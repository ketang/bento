---
name: closure
description: |
  Use when cleaning up leftover git state after interrupted or completed work.
  Scans branches, worktrees, stashes, and working-tree changes, produces
  structured evidence, and only applies clearly safe cleanup in explicit apply
  mode.
recommended_model: high
---

# Closure

## Model Guidance

Recommended model: high.

Use a high-capability model when cleanup decisions could discard useful state.
A mid-tier model is acceptable only for dry-run scanning or tightly supervised
safe cleanup.

Use this skill when a repo needs a closeout pass over leftover git state from
prior agent or human work.

Keep this skill generic. If the repo config or local conventions indicate a
specific tracker or primary-branch workflow, open the matching companion doc
before acting:

- `references/beads.md` for Beads tracker correlation and closure
- `references/github-issues.md` for GitHub Issues correlation and closure
- `references/primary-branch-sync.md` for repos that explicitly want local
  primary-branch sync and validation behavior

## Deterministic Helper

This skill includes `scripts/closure-scan.py` for the git-state discovery and
the narrow cleanup actions that can be made deterministic.

Run the scan first:

```bash
python3 scripts/closure-scan.py
```

Use the JSON output as the base layer for:

- the detected primary branch
- local branches that are actually merged into the primary branch and safe to
  delete
- patch-equivalent branches whose changes appear landed but whose history still
  needs review
- active worktrees, stashes, and working-tree changes

If the user wants the clearly safe local branch cleanup applied, run:

```bash
python3 scripts/closure-scan.py --apply delete-local-merged-branches
```

This apply mode deletes only local branches that are both:

- fully merged into the detected primary branch
- not the primary branch and not checked out in any worktree

Everything else remains review-driven.

## Usage

- Invoke `closure` for a full scan of the current repo.
- Keep the first pass dry-run unless the user explicitly wants cleanup applied.

## Workflow

1. Run the helper in dry-run mode to detect the primary branch and collect
   structured git state.
2. If the repo config or local conventions require tracker-aware or
   primary-branch-sync behavior, open the matching companion doc before acting.
3. Fetch remote state if the repo and environment allow it, then inspect local
   and remote divergence where relevant.
4. Review the helper output and categorize findings:
   - local branches safe to delete immediately
   - patch-equivalent or unmerged branches that need analysis
   - active worktrees
   - stashes
   - working-tree changes
   - stale tracker items whose work appears landed
   - for tracker items, collect the branch, commit, diff, or merge evidence
     that supports either closing the item or leaving it open
   - when the evidence is ambiguous, summarize the situation with a compact
     recommendation taxonomy:
     - `duplicate`: another branch or item clearly covers the same work
     - `superseded`: a newer branch or change makes this obsolete
     - `incomplete but valuable`: worth finishing or handing off to `land-work`
     - `conflicted`: likely valuable, but currently blocked by merge or state
       conflicts
     - `unknown`: evidence is insufficient for a stronger recommendation
   - treat those labels as review guidance only; the helper output still
     determines what is safe to delete
5. If a branch appears valuable, complete, and likely ready to land, present
   the evidence and recommend invoking `land-work` from that feature-branch
   worktree rather than describing a separate landing procedure here.
6. If a tracker item appears complete because its work is already landed,
   present the evidence and hand off to the repo's tracker workflow skill to
   close or update it rather than mutating tracker state directly inside
   `closure`.
   - If the repo uses Beads, invoke `beads-issue-flow`.
   - If the repo uses GitHub Issues, invoke `github-issue-flow`.
   - If the tracker workflow is unclear, stop at the evidence and proposed
     action instead of guessing.
7. Present evidence before any destructive step that falls outside the helper's
   explicit apply mode.
8. If the user wants safe local branch cleanup, run the helper's apply mode and
   report the deleted branches.
9. Summarize the remaining artifacts and recommend a recovery or closeout plan
   biased toward finishing or landing incomplete work rather than discarding it.

## Handoff To Land Work

When `closure` finds a branch whose work appears valuable and complete, hand off
explicitly to `land-work` for the landing flow.

Include in the handoff:

- the branch name and worktree location
- the evidence that the work appears landing-ready
- any remaining checks or open questions
- a direct instruction to invoke `land-work` from that feature-branch worktree

Do not restate `land-work`'s rebase, lease-verification, or merge procedure
inside `closure`.

## Handoff To Tracker Workflow

When `closure` finds a tracker item whose work appears landed, hand off
explicitly to the repo's tracker workflow skill rather than closing the item
inside `closure`.

Include in the handoff:

- the tracker item identifier
- the correlated branch, worktree, or landed commit evidence
- whether the recommended action is `close`, `update`, or `leave open`
- any uncertainty that still requires human review

Tracker-specific skills own the actual mutation:

- `beads-issue-flow` for Beads repositories
- `github-issue-flow` for GitHub Issues repositories

## Output Style

Produce output progressively while scanning and cleaning. Narrate findings by
phase and ground the recommendations in the helper output rather than vague git
intuition.

## Safety

- Always start with dry-run output from the helper.
- Do not assume syncing and pushing the primary branch is always required.
- Do not force-push or rebase the primary branch without explicit approval.
- Do not improvise a separate branch-landing procedure inside `closure` when
  `land-work` applies.
- Do not run tracker-specific close commands directly inside `closure`; use the
  repo's tracker workflow skill after presenting evidence.
- Do not auto-delete worktrees, stashes, or patch-equivalent branches.
- Do not delete unmerged work or close tracker items without presenting
  evidence and the proposed action first.
