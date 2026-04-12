---
name: closure
description: Use when cleaning up leftover git state after interrupted or completed work — branches, worktrees, stashes, and uncommitted changes.
recommended_model: high
---

# Closure

## Model Guidance

Recommended model: high — cleanup decisions can discard useful state, and
liveness inference across worktrees requires careful evidence weighing. A
mid-tier model is acceptable only for dry-run scanning or tightly supervised
safe cleanup.

Use this skill when a repo needs a closeout pass over leftover git state from
prior agent or human work. The most important case is **dead-agent worktrees**:
worktrees created by agents that have since died, completed, or crashed, which
may contain landed work, work-in-progress, or uncommitted state from a failed
run. The presence of uncommitted changes in a worktree is *not* evidence of a
live agent — a crashed machine or a failed run both leave dirty trees.

Keep this skill generic. If the repo config or local conventions indicate a
specific tracker or primary-branch workflow, open the matching companion doc
before acting:

- `references/beads.md` for Beads tracker correlation and closure
- `references/github-issues.md` for GitHub Issues correlation and closure
- `references/primary-branch-sync.md` for repos that explicitly want local
  primary-branch sync and validation behavior

## Deterministic Helper

This skill includes `closure/scripts/closure-scan.py` for git-state discovery
and narrow deterministic cleanup actions. Invoke by script path, not
`python3 <script>`, so approvals stay scoped.

Run the scan first:

```bash
closure/scripts/closure-scan.py
```

The helper emits a JSON object with the detected primary branch, per-branch
classification, per-worktree liveness assessment (overnight-aware activity
timing, session log evidence, live-process detection), stashes, and
working-tree changes. See `closure/references/helper-output.md` for the
branch-classification enum, liveness-verdict enum, and recency calculation.

If the user wants the clearly safe local branch cleanup applied:

```bash
closure/scripts/closure-scan.py --apply delete-local-merged-branches
```

This apply mode deletes:

- local branches whose classification is `safe_to_delete`
- linked worktrees attached to `merged_checked_out` branches when the worktree
  is clean and its liveness verdict is `stale` or `unknown`, then deletes the
  merged branch after the worktree removal succeeds

Everything else remains review-driven.

Add `--no-liveness` for a faster scan that skips session log scanning and
process detection, returning git state only.

### Branch Classifications

| Classification | Meaning |
|---|---|
| `primary` | The primary branch |
| `safe_to_delete` | Merged into primary; not in any worktree |
| `merged_checked_out` | Merged into primary; still checked out in a worktree — worktree is a cleanup candidate |
| `checked_out_in_worktree` | Not yet merged; checked out in a linked worktree — needs investigation |
| `patch_equivalent_review` | No unique patches vs primary; not in a worktree |
| `review_required` | Unmerged work not in a worktree |

### Liveness Verdicts

The `liveness.verdict` field on each worktree is one of:

| Verdict | Meaning |
|---|---|
| `confirmed_live` | A process with this worktree as CWD is running now |
| `possibly_live` | Recent activity AND a session log exists — treat as live |
| `recently_active` | Recent activity but no corroborating session log |
| `stale` | Session log exists but activity is old; no live process |
| `unknown` | No session evidence, no process — only git/file timestamps |

**Important limitation**: an agent blocked waiting for user input may show no
file or commit activity for many hours while still running.  `confirmed_live`
(live process detected) is the only signal that reliably distinguishes this
case.  All other verdicts are probabilistic.  Outside the helper's explicit
apply mode, when `verdict` is `possibly_live`, `recently_active`, or `unknown`,
present the evidence and ask the user rather than acting unilaterally.

### Recency Calculation

The helper calculates `active_seconds_since_activity` using an overnight-aware
clock that excludes 11pm–8am local time from the elapsed total.  This means
activity at 10:45pm and a check at 8:15am produces ~30 active minutes, not
~9.5 hours.  A worktree is considered recently active if
`active_seconds_since_activity` is under 2 hours (7200 seconds).

Last activity is the maximum of: the HEAD commit timestamp and the mtime of any
tracked file with uncommitted changes.  Untracked files are excluded.
## Usage

- Invoke `closure` for a full scan of the current repo.
- Keep the first pass dry-run unless the user explicitly wants cleanup applied.
- Do not stop at reporting findings from a dry-run scan. End by presenting the
  safest supported next actions and asking the user to choose one.
- **Never treat "no safe_to_delete branches" as a complete result when linked
  worktrees are present.** Worktrees are the primary subject of investigation.

## Workflow

1. Run the helper in dry-run mode to detect the primary branch and collect
   structured git state.
2. If the repo config or local conventions require tracker-aware or
   primary-branch-sync behavior, open the matching companion doc before acting.
3. Fetch remote state if the repo and environment allow it, then inspect local
   and remote divergence where relevant.
4. Review the helper output and categorize findings (local branches safe to
   delete, patch-equivalent or unmerged branches needing analysis, linked
   worktrees, stashes, working-tree changes, stale tracker items). For tracker
   items, collect the branch/commit/diff/merge evidence that supports either
   closing the item or leaving it open. Label ambiguous findings using the
   taxonomy in `closure/references/recommendation-taxonomy.md`.
5. For each linked worktree, assess liveness and value using the decision tree
   in `closure/references/worktree-triage.md`. Uncommitted state is never
   affirmative liveness evidence.
6. If a branch appears valuable, complete, and likely ready to land, present
   the evidence and recommend invoking `land-work` from that feature-branch
   worktree rather than describing a separate landing procedure here.
7. If a tracker item appears complete because its work is already landed,
   present the evidence and hand off to the repo's tracker workflow skill
   (`beads-issue-flow` or `github-issue-flow`) to close or update it rather
   than mutating tracker state directly inside `closure`. If the tracker
   workflow is unclear, stop at evidence and proposed action instead of
   guessing.
8. Present evidence before any destructive step that falls outside the
   helper's explicit apply mode.
9. If the user wants safe local branch cleanup, run the helper's apply mode
   and report the deleted branches.
10. End every dry-run pass with a clear next-step choice for the user: apply
    safe local branch cleanup, inspect or preserve working-tree changes, hand
    off a landing-ready branch to `land-work`, hand off a landed tracker item
    to the tracker workflow skill, or leave everything unchanged. If only one
    action is justified, present that recommendation and ask for explicit
    confirmation before applying it.

## Handoffs

When `closure` finds work that belongs to another skill, hand off with
evidence rather than restating that skill's procedure.

**To `land-work`** (branch appears valuable and complete): branch name,
worktree location, evidence the work is landing-ready, remaining checks or
open questions, and a direct instruction to invoke `land-work` from that
feature-branch worktree. Do not restate `land-work`'s rebase,
lease-verification, or merge procedure here.

**To the tracker workflow skill** (`beads-issue-flow` or `github-issue-flow`)
when a tracker item's work appears landed: tracker item identifier, correlated
branch/worktree/commit evidence, whether the recommended action is `close`,
`update`, or `leave open`, and any uncertainty that still requires human
review. Tracker-specific skills own the actual mutation.

## Output Style

Produce output progressively while scanning and cleaning. Narrate findings by
phase and ground recommendations in the helper output rather than vague git
intuition. When the scan remains in dry-run mode, end with a concise, explicit
next-step choice over an open-ended summary.

## Safety

- Always start with dry-run output from the helper.
- Do not force-push or rebase the primary branch without explicit approval.
- Do not auto-delete worktrees, stashes, or patch-equivalent branches.
- Do not delete unmerged work or close tracker items without presenting
  evidence and the proposed action first.
- Do not treat absence of a live process or recent activity as proof that a
  worktree is safe to discard — an agent waiting for input may be idle for
  hours.
- **Never construct manual `git branch -D` or `git branch -d` commands.** All
  branch deletion must go through the helper's
  `--apply delete-local-merged-branches` mode. Manually scripted deletion
  loops bypass the helper's safety checks and can trigger Claude Code
  rendering errors.
- **Never combine multiple shell operations in one `Bash` command** using
  `&&`, pipes, `$(...)`, or inline interpreters. Issue one command per tool
  call. Compound commands can trigger Claude Code "Unhandled node type"
  errors.
