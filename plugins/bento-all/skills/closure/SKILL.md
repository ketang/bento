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
5. Present evidence before any destructive step that falls outside the helper's
   explicit apply mode.
6. If the user wants safe local branch cleanup, run the helper's apply mode and
   report the deleted branches.
7. Summarize the remaining artifacts and recommend a recovery or closeout plan
   biased toward finishing or landing incomplete work rather than discarding it.

## Output Style

Produce output progressively while scanning and cleaning. Narrate findings by
phase and ground the recommendations in the helper output rather than vague git
intuition.

## Safety

- Always start with dry-run output from the helper.
- Do not assume syncing and pushing the primary branch is always required.
- Do not force-push or rebase the primary branch without explicit approval.
- Do not auto-delete worktrees, stashes, or patch-equivalent branches.
- Do not delete unmerged work or close tracker items without presenting
  evidence and the proposed action first.
