---
name: closure
description: |
  Examine a git repo for leftover branches, worktrees, stashes, and working-set
  changes from prior Claude sessions. Auto-cleans merged work, analyzes
  unmerged work, and recommends a plan of action biased toward finishing
  incomplete work.
---

# Closure

Find and resolve leftover git artifacts from prior Claude or human sessions.

Keep this skill generic. If the repo config or local conventions indicate a
specific tracker or primary-branch workflow, open the matching companion doc
before acting:

- `references/beads.md` for Beads tracker correlation and closure
- `references/primary-branch-sync.md` for repos that explicitly want local
  primary-branch sync and validation behavior

## Usage

- `/closure` for a full scan and cleanup of the current repo

## Workflow

1. Detect the primary branch using project config, remote default branch, or a
   local heuristic.
2. Fetch remote state and inspect local and remote divergence.
3. Discover worktrees, local branches, remote branches, stashes, and working
   directory changes.
4. Detect merged branches using merge metadata and content-equivalence checks.
5. If the repo has a documented tracker, correlate branches and task state.
6. Categorize findings:
   - merged work safe to clean
   - unmerged work that needs analysis
   - stashes
   - working directory changes
   - stale open or in-progress tasks whose work already landed
7. Auto-clean only the merged and clearly safe artifacts.
8. Summarize the remaining unmerged work and recommend a recovery or closeout
   plan.

## Output Style

Produce output progressively while scanning and cleaning. Narrate findings by
phase so the user can see what the skill is doing in real time.

## Safety

- Do not assume syncing and pushing the primary branch is always required.
- Do not force-push or rebase the primary branch without explicit approval.
- Do not delete unmerged work without presenting evidence and the proposed
  action first.
