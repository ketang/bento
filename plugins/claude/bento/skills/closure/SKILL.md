---
name: closure
description: Do NOT use to clean up your own active or just-finished work — that is land-work's job, including removing your worktree and branch after the merge. Use only as a periodic garbage-collection pass over OTHER agents' abandoned or crashed git state — dead-agent branches, worktrees, stashes, and uncommitted work.
---

# Closure

## When NOT to use

Closure is a GC pass. It is **not** the cleanup path for the calling agent's
own work:

- **Just merged your own branch?** Run `land-work`; its post-merge cleanup
  removes the branch and worktree it owns. Don't reach for closure to tear down
  your own just-landed worktree.
- **Mid-task and want to discard your own work?** Exit the worktree, then run
  `git worktree remove --force` (a dirty worktree refuses a plain remove) and
  `git branch -D` directly.
- **Routine after every task?** No. Closure sweeps up state left by agents that
  crashed, were abandoned, or whose `land-work` cleanup did not run — periodic
  GC, not a per-task step.

The helper detects self-invocation (your own agent's process tree has a cwd
inside one of the scanned worktrees) and surfaces a `self_invocation: true`
flag plus a pointed apply-mode skip reason directing you to `land-work`.

## Model Guidance

Recommended model: high — cleanup decisions can discard useful state, and
liveness inference across worktrees requires careful evidence weighing. A
mid-tier model is acceptable only for dry-run scanning or tightly supervised
safe cleanup.

Use this skill when a repo needs a closeout pass over leftover git state. The
most important case is **dead-agent worktrees** — created by agents that died,
completed, or crashed — which may hold landed work, work-in-progress, or
uncommitted state from a failed run.

If the repo config or local conventions indicate a specific tracker or
primary-branch workflow, open the matching companion doc before acting:

- `../land-work/references/workflow-invariants.md` for shared primary-branch wording,
  tracker mutation timing, and linked-worktree cleanup order
- `references/beads.md` for Beads tracker correlation and closure
- `references/github-issues.md` for GitHub Issues correlation and closure
- `references/primary-branch-sync.md` for repos that explicitly want local
  primary-branch sync and validation behavior

## Deterministic Helper

This skill includes `closure/scripts/closure-scan.py` for git-state discovery
and deterministic cleanup. Invoke by script path, not `python3 <script>`, so
approvals stay scoped.

Run the scan first:

```bash
closure/scripts/closure-scan.py
```

The helper emits a JSON object with the detected primary branch, per-branch
classification, per-worktree liveness assessment, stashes, and working-tree
changes. See `closure/references/helper-output.md` for the
branch-classification enum, liveness-verdict enum, apply-mode cleanup order,
and recency calculation.

If the user wants the clearly safe local branch cleanup applied:

```bash
closure/scripts/closure-scan.py --apply delete-local-merged-branches
```

This deletes `safe_to_delete` branches and removes clean `merged_checked_out`
worktrees before deleting their branch — the approved automatic cleanup path.
See `closure/references/helper-output.md` for the full liveness, dirty-tree, and
self-invocation gates and skip conditions.

### Single-Target Mode

`--target-branch` scopes the apply pass to one named branch — a specific stale,
ambiguous, or other-agent leftover, or a fallback diagnostic after direct
cleanup fails:

```bash
closure/scripts/closure-scan.py --target-branch <name> --apply delete-local-merged-branches
```

The full scan still runs (JSON output shape unchanged), but the apply pass
touches only the named branch; other `safe_to_delete` and `merged_checked_out`
branches are ignored. All safety gates (clean worktree, liveness verdict) still
apply. A target absent locally exits non-zero; one that exists but is ineligible
records a `skipped_actions` entry (classification in the reason) and exits 0.

Single-target mode is **not** the routine cleanup path for the agent that just
landed its own branch — that is `land-work` step 10's direct cleanup (see
**When NOT to use**). If you invoke closure from inside your own worktree, its
self-invocation gate redirects you to `land-work`.
`--target-branch` narrows scan and apply scope only; it does not override the
same-session prohibition on the caller's own active or just-finished worktree.
The wide-net workflow below is for repo-wide passes, not single-branch
tear-down.

If the user also wants patch-equivalent branches removed (work landed via
rebase or squash with no merge commit):

```bash
closure/scripts/closure-scan.py --apply delete-local-patch-equivalent-branches
```

This force-deletes patch-equivalent branches (zero unique patches vs primary)
via `git branch -D`; safe because `unique_patch_count == 0` confirms all content
is already on primary. For a patch-equivalent branch checked out in a worktree,
the worktree is removed first under the same safety gates. See
`closure/references/helper-output.md`.

Everything else remains review-driven.

Add `--no-liveness` for a faster scan that skips session log scanning and
process detection, returning git state only.

### Branch Correlation (review_required triage)

When a `review_required` branch needs disposition (genuine outstanding work vs.
landed-under-different-SHA vs. abandoned re-implementation), opt into raw
signal collection:

```bash
closure/scripts/closure-scan.py --correlate-branches
```

Off by default (`git cherry` across many branches is slow). Each
`review_required` branch entry then carries a `correlation` block. See
`closure/references/helper-output.md` for the correlation field list, tracker
auto-detection precedence (JIRA needs `JIRA_BASE_URL` + `JIRA_API_TOKEN` +
`JIRA_USER_EMAIL`), and the `--tracker`/`--issue-pattern` overrides.

#### Decision matrix

Apply this matrix per branch. Heuristic deletions are **never** batched —
present the evidence and proposed action, then ask the user.

| `cherry_unique_count` | `tracker_status` | grep on primary | Proposed action |
|---|---|---|---|
| 0 | `closed` | hits | Landed under a different SHA. Recommend delete; ask before deleting. |
| 0 | `open` | hits | Patches landed but tracker still open. Recommend delete branch + hand off to tracker skill to close. |
| 0 | (any/null) | hits | Landed under a different SHA. Recommend delete; ask before deleting. |
| > 0 | `closed` | hits | Issue done but this branch's code never merged — likely abandoned re-implementation. Spot-check, then ask before deleting. |
| > 0 | `open` | none | Genuine outstanding work. Keep. |
| > 0 | `open` | hits | Partial overlap. Surface to user; do not delete. |
| > 0 | `null` | none | No tracker context. Surface to user; do not delete. |

A `0` cherry count matches the `patch_equivalent_review` classification (when
not in a worktree), already handled by
`--apply delete-local-patch-equivalent-branches`. Correlation covers the
`review_required` rows above, where deletion stays review-driven.

### Liveness Verdicts

See `closure/references/helper-output.md` for the `liveness.verdict` enum and
its important limitation: an agent blocked waiting for user input can look idle
for hours, so `confirmed_live` (live process detected) is the only reliable
liveness signal; every other verdict is probabilistic.

Outside the helper's explicit apply mode, treat `possibly_live`,
`recently_active`, and `unknown` as review-driven: present the evidence and ask
before manual cleanup. Inside `--apply delete-local-merged-branches`, `unknown`
is eligible for automatic cleanup only when the branch is `merged_checked_out`
and the worktree is clean.

## Usage

- Invoke `closure` for a full scan of the current repo.
- Keep the first pass dry-run unless the user explicitly wants cleanup applied.
- End a dry-run pass by presenting the safest supported next actions for the
  user to choose from. **Never treat "no safe_to_delete branches" as a complete
  result when linked worktrees are present** — worktrees are the primary
  subject of investigation.

## Anti-Rationalization

| Excuse | Counter-argument |
|---|---|
| "I just landed my own branch; closure can clean up the rest." | `land-work` owns routine cleanup for the active agent's just-landed branch. Closure is for other-agent or stale leftovers, and its self-invocation/liveness gates are expected to reject your own recent worktree. |
| "The worktree has no live process, so it is safe to delete." | Absence of a live process is not proof of abandonment. An agent may be waiting for user input, and `possibly_live`, `recently_active`, and `unknown` findings remain review-driven outside the helper's explicit apply mode. |
| "The branch is merged, so I can delete it manually during this closure pass." | In a closure GC pass, merged other-agent branches with linked worktrees require ordered cleanup through the helper apply mode; manual `git branch -d`/`-D` here bypasses the helper's classification, liveness, and worktree-order checks. Your own just-landed branch is `land-work` step 10's direct manual cleanup, not a closure pass. |
| "The tracker item looks done; I can close it during cleanup." | Closure gathers and presents landing evidence, then hands tracker mutation to the tracker workflow skill. Tracker items close only after verified landing on the integration branch. |
| "This is only a dry-run scan, so I can stop after saying nothing is safe to delete." | A dry-run pass must still account for linked worktrees, stashes, unmerged branches, and next actions. Linked worktrees are the main investigation target, not an optional appendix. |

## Workflow

1. Run the helper in dry-run mode to detect the primary branch and collect
   structured git state.
2. If tracker-aware or primary-branch-sync behavior is required, open the
   matching companion doc (listed above) before acting.
3. Fetch remote state if the repo and environment allow it, then inspect local
   and remote divergence where relevant.
4. Review the helper output and categorize findings (branches safe to delete,
   patch-equivalent or unmerged branches, linked worktrees, stashes,
   working-tree changes, stale tracker items). For tracker items, collect the
   branch/commit/diff/merge evidence supporting close or leave-open. Label
   ambiguous findings using the taxonomy in
   `closure/references/recommendation-taxonomy.md`.
5. For each linked worktree, assess liveness and value using the decision tree
   in `closure/references/worktree-triage.md`. Uncommitted state is never
   affirmative liveness evidence.
6. If a branch appears valuable, complete, and likely ready to land, hand it
   off to `land-work` per **Handoffs** below.
7. If a tracker item's work is already landed, hand it off to the tracker
   workflow skill per **Handoffs** below. Follow
   `../land-work/references/workflow-invariants.md`: mutate tracker state only
   after the work is verified as landed on the detected primary branch. If the
   tracker workflow is unclear, stop at evidence and proposed action.
8. Present evidence before any destructive step that falls outside the
   helper's explicit apply mode.
9. If the user wants safe local branch cleanup, run the helper's apply mode
   and report the deleted branches.
10. End every dry-run pass with a clear next-step choice: apply safe local
    branch cleanup, inspect or preserve working-tree changes, hand off to
    `land-work` or the tracker workflow skill, or leave everything unchanged.
    If only one action is justified, present it and ask for explicit
    confirmation before applying.
11. End at the repository root on the detected primary branch, not in a
    feature-branch worktree.

## Handoffs

When `closure` finds work that belongs to another skill, hand off with
evidence rather than restating that skill's procedure.

**To `land-work`** (branch appears valuable and complete): branch name,
worktree location, evidence the work is landing-ready, and remaining checks or
open questions; instruct invoking `land-work` from that feature-branch worktree.

**To the tracker workflow skill** (`beads-issue-flow` or `github-issue-flow`,
when a tracker item's work appears landed): item identifier, correlated
branch/worktree/commit evidence, the recommended action (`close`, `update`, or
`leave open`), and any uncertainty needing human review.

## Output Style

Produce output progressively while scanning: narrate findings by phase and
ground recommendations in the helper output, not vague git intuition. Confirm
the final repo-root, primary-branch shell state.

## Safety

- Always start with dry-run output from the helper.
- Do not force-push or rebase the primary branch without explicit approval.
- Do not auto-delete stashes.
- Do not delete patch-equivalent branches outside the helper's
  `--apply delete-local-patch-equivalent-branches` mode.
- Do not delete worktrees except through the helper's
  `--apply delete-local-merged-branches` mode for clean
  `merged_checked_out` worktrees that satisfy the helper's liveness gate.
- Do not delete a merged branch before removing its linked worktree.
- Do not delete unmerged work or close tracker items without presenting
  evidence and the proposed action first.
- Do not treat absence of a live process or recent activity as proof that a
  worktree is safe to discard — an agent waiting for input may be idle for
  hours.
- **During a closure GC pass, never construct manual `git branch -D` or
  `git branch -d` commands.** All branch deletion in a closure pass must go
  through the helper's apply modes (`--apply delete-local-merged-branches` or
  `--apply delete-local-patch-equivalent-branches`); manually scripted deletion
  loops bypass the helper's safety checks. This scopes to closure's sweep of
  other-agent leftovers and does not override `land-work` step 10, where the
  agent that just landed its own branch removes its own worktree and runs
  `git branch -d` directly.
- **Never combine multiple shell operations in one command** using `&&`, pipes,
  `$(...)`, or inline interpreters. Issue one command per tool call.

## Claude Code Requirements

In Claude Code, manually scripted deletion loops and compound `Bash` commands
can trigger "Unhandled node type" rendering errors. Keep cleanup commands as
single helper invocations or one shell step per tool call.
