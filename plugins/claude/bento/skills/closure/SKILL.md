---
name: closure
description: Use as an eventual garbage-collection pass over OTHER agents' leftover git state — dead-agent branches, worktrees, stashes, and uncommitted work. Not for cleaning up your own active or just-finished work; use land-work for that.
recommended_model: high
---

# Closure

## When NOT to use

Closure is a GC pass. It is **not** the cleanup path for the calling agent's
own work:

- **Just merged your own branch?** Run `land-work` — its post-merge cleanup
  removes the branch and worktree it owns. Calling closure to delete your own
  worktree leaves the worktree behind because the helper correctly refuses
  to delete a recently-active or self-invoked worktree.
- **Mid-task and want to discard your own work?** Exit the worktree, then use
  `git worktree remove` and `git branch -D` directly. Closure will not delete
  a worktree whose call-site is your own agent.
- **Routine after every task?** No. Closure is for sweeping up state left
  behind by agents that crashed, were abandoned, or whose `land-work` cleanup
  did not run. Treat it as periodic GC, not a per-task step.

The helper detects self-invocation (your own agent's process tree has a cwd
inside one of the scanned worktrees) and surfaces a `self_invocation: true`
flag plus a pointed apply-mode skip reason directing you to `land-work`.

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

- `../land-work/references/workflow-invariants.md` for shared primary-branch wording,
  tracker mutation timing, and linked-worktree cleanup order
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
branch-classification enum, liveness-verdict enum, apply-mode cleanup order,
and recency calculation.

If the user wants the clearly safe local branch cleanup applied:

```bash
closure/scripts/closure-scan.py --apply delete-local-merged-branches
```

This apply mode deletes:

- local branches whose classification is `safe_to_delete`
- linked worktrees attached to `merged_checked_out` branches when the worktree
  is clean and its liveness verdict is `stale` or `unknown`, then deletes the
  merged branch after the worktree removal succeeds

For merged, clean, stale-or-unknown linked worktrees, this helper apply mode is
the approved automatic cleanup path.

### Single-Target Mode

When another skill (notably `land-work`) already knows the exact branch to
clean up after a successful merge, scope the apply pass with `--target-branch`:

```bash
closure/scripts/closure-scan.py --target-branch <name> --apply delete-local-merged-branches
```

The full scan still runs and the JSON output is unchanged in shape, but the
apply pass operates on the named branch only — other `safe_to_delete` and
`merged_checked_out` branches are ignored. All safety gates (clean worktree,
liveness verdict, in-flight launch-work log) still apply. If the target branch
does not exist locally, the helper exits non-zero. If the target exists but is
not eligible (wrong classification), the helper records a single
`skipped_actions` entry with the classification in the reason and exits 0; the
caller decides what to do with that signal.

Use single-target mode for handoffs from skills that have already verified the
landing. The wide-net workflow below is for repo-wide cleanup passes, not for
single-branch tear-down.

If the user also wants patch-equivalent branches removed (work landed via
rebase or squash with no merge commit):

```bash
closure/scripts/closure-scan.py --apply delete-local-patch-equivalent-branches
```

This apply mode force-deletes local branches whose classification is
`patch_equivalent_review` — branches with zero unique patches relative to
primary that are not checked out in any worktree. These branches are not
reachable ancestors of primary (hence no merge record), so the helper uses
`git branch -D`. The force delete is safe because `unique_patch_count == 0`
confirms all content is already on primary.

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

Off by default — `git cherry` across many branches is slow. Each
`review_required` branch entry then carries a `correlation` block:

- `issue_id` — extracted from the branch name and confirmed by tracker lookup;
  `null` if the regex matches noise the tracker does not recognize
- `cherry_unique_count` / `cherry_equivalent_count` — `git cherry` `+`/`-` lines
- `main_commits_referencing_issue` — short SHAs on primary whose commit message
  mentions the issue id (bounded by merge-base date)
- `tracker_status` — `null`, or the tracker's status string (e.g. `closed`,
  `open`, `in_progress`)
- `merge_base_age_days`, `divergence_ahead`, `divergence_behind`

Tracker auto-detection: `.beads/` → beads; else JIRA env vars
(`JIRA_BASE_URL` + `JIRA_API_TOKEN` + `JIRA_USER_EMAIL`) → jira; else
`.github/` + `gh` CLI → gh; else none. Override with
`--tracker {beads,gh,jira,none}`. Override the issue-id regex with
`--issue-pattern <regex>` when the tracker default does not fit the repo's
branch convention.

#### Decision matrix

The agent applies this matrix per branch. Heuristic deletions are **never**
batched — present the evidence and the proposed action, then ask the user.

| `cherry_unique_count` | `tracker_status` | grep on primary | Proposed action |
|---|---|---|---|
| 0 | `closed` | hits | Landed under a different SHA. Recommend delete; ask before deleting. |
| 0 | `open` | hits | Patches landed but tracker still open. Recommend delete branch + hand off to tracker skill to close. |
| 0 | (any/null) | hits | Landed under a different SHA. Recommend delete; ask before deleting. |
| > 0 | `closed` | hits | Issue done but this branch's code never merged — likely abandoned re-implementation. Spot-check, then ask before deleting. |
| > 0 | `open` | none | Genuine outstanding work. Keep. |
| > 0 | `open` | hits | Partial overlap. Surface to user; do not delete. |
| > 0 | `null` | none | No tracker context. Surface to user; do not delete. |

A `0` cherry count corresponds to the existing `patch_equivalent_review`
classification when the branch is not in a worktree, and the
`--apply delete-local-patch-equivalent-branches` mode already handles it.
Correlation is for the `review_required` rows above where deletion remains
review-driven.

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
file or commit activity for many hours while still running. `confirmed_live`
(live process detected) is the only signal that reliably distinguishes this
case. All other verdicts are probabilistic.

Outside the helper's explicit apply mode, treat `possibly_live`,
`recently_active`, and `unknown` as review-driven: present the evidence and ask
the user before manual cleanup. Inside
`--apply delete-local-merged-branches`, `unknown` is eligible for automatic
cleanup only when the branch is `merged_checked_out` and the worktree is clean.

### Recency Calculation

The helper calculates `active_seconds_since_activity` using an overnight-aware
clock that excludes 11pm–8am local time from the elapsed total.  This means
activity at 10:45pm and a check at 8:15am produces ~30 active minutes, not
~9.5 hours.  A worktree is considered recently active if
`active_seconds_since_activity` is under 2 hours (7200 seconds).

Last activity is the maximum of: the HEAD commit timestamp and the mtime of any
tracked file with uncommitted changes.  Untracked files are excluded.

### Launch-Work Progress Logs

When a worktree contains `.launch-work/log.md`, the helper emits a
`launch_work` object on that worktree entry with `present`, `last_updated`,
and `checkpoint`. The presence of an in-flight log
(`checkpoint != "ready-to-land"`) is **affirmative** evidence that the
worktree is mid-task — unlike uncommitted state, which is not.

`--apply delete-local-merged-branches` never deletes a worktree with an
in-flight log, even when liveness is `stale` or `unknown`. The skip reason
(`launch-work log in flight (checkpoint=<name>)`) is surfaced in the
apply-mode output.

A `ready-to-land` log on a merged branch is an anomaly — `land-work`'s
cleanup pass did not run. Surface it to the user before any cleanup action.

When a dry-run pass finds any worktree with an in-flight log, the next-step
menu must include **resume in-flight launch-work** alongside the existing
options (apply safe cleanup, hand off to `land-work`, leave unchanged).

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
   than mutating tracker state directly inside `closure`. Follow
   `../land-work/references/workflow-invariants.md`: mutate tracker state only
   after the work is verified as landed on the detected primary branch. If the
   tracker workflow is unclear, stop at evidence and proposed action instead of
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
11. End at the repository root on the detected primary branch rather than in a
    feature-branch worktree.

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
next-step choice over an open-ended summary. Confirm the final repo-root,
primary-branch shell state.

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
- **Never construct manual `git branch -D` or `git branch -d` commands.** All
  branch deletion must go through the helper's apply modes
  (`--apply delete-local-merged-branches` or
  `--apply delete-local-patch-equivalent-branches`). Manually scripted
  deletion loops bypass the helper's safety checks and can trigger Claude Code
  rendering errors.
- **Never combine multiple shell operations in one `Bash` command** using
  `&&`, pipes, `$(...)`, or inline interpreters. Issue one command per tool
  call. Compound commands can trigger Claude Code "Unhandled node type"
  errors.
