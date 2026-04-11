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
prior agent or human work.  The most important case is **dead-agent worktrees**:
worktrees created by agents that have since died, completed, or crashed, which
may contain landed work, work-in-progress, or uncommitted state from a failed
run.  The presence of uncommitted changes in a worktree is *not* evidence of a
live agent — a crashed machine or a failed run both leave dirty trees.

Keep this skill generic. If the repo config or local conventions indicate a
specific tracker or primary-branch workflow, open the matching companion doc
before acting:

- `references/beads.md` for Beads tracker correlation and closure
- `references/github-issues.md` for GitHub Issues correlation and closure
- `references/primary-branch-sync.md` for repos that explicitly want local
  primary-branch sync and validation behavior

## Deterministic Helper

This skill includes `closure/scripts/closure-scan.py` for the git-state
discovery and the narrow cleanup actions that can be made deterministic.
Invoke this helper by script path, not `python3 <script>`, so approvals stay
scoped to the script.

Run the scan first:

```bash
closure/scripts/closure-scan.py
```

The helper emits a JSON object that includes:

- the detected primary branch
- per-branch classification (see Branch Classifications below)
- per-worktree liveness assessment with overnight-aware activity timing,
  session log evidence, and live-process detection
- stashes and working-tree changes

If the user wants the clearly safe local branch cleanup applied, run:

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
  worktrees are present.**  Worktrees are the primary subject of investigation.

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
   - linked worktrees (see step 4a)
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

4a. **For each linked worktree, assess liveness and value:**

   A worktree is treated as **live** only if there is affirmative evidence: a
   running process holding the worktree as its CWD (`confirmed_live`), or recent
   activity combined with an open session log (`possibly_live`).  Uncommitted
   working-tree changes are **not** affirmative evidence of liveness — a crashed
   machine, a failed run, or an agent that wrote files and then died all leave
   dirty trees.

   Apply this decision tree:

   - `confirmed_live` → do not touch; note the worktree is actively in use
   - `possibly_live` or `recently_active` → present the liveness signals to the
     user and ask before taking any action; the agent may be waiting for input
   - `stale` or `unknown` with `merged_checked_out` branch → the useful work is
     already in primary; recommend removing the worktree
   - `stale` or `unknown` with unmerged branch → investigate commits and diff
     vs. primary; classify as `incomplete but valuable`, `superseded`,
     `conflicted`, or `unknown`; recommend `land-work` if appropriate
   - dirty working tree in a stale/unknown worktree → summarize the uncommitted
     changes (file list, rough diff size) so the user can judge salvage value;
     do not discard without presenting the evidence

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
10. End every dry-run pass with a clear next-step choice for the user instead
    of a passive summary.
    - Include only actions supported by the evidence from the current scan.
    - Prefer a compact choice set such as:
      - apply safe local branch cleanup
      - inspect or preserve working-tree changes
      - hand off a landing-ready branch to `land-work`
      - hand off a landed tracker item to the tracker workflow skill
      - leave everything unchanged for now
    - If only one action is actually justified, present that recommendation and
      ask for explicit confirmation before applying it.

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

When the scan remains in dry-run mode, end with a concise, explicit next-step
choice for the user. Prefer a short, concrete set of supported actions over an
open-ended summary.

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
- Do not treat dirty working-tree state as evidence that a worktree is live.
- Do not treat absence of a live process or recent activity as proof that a
  worktree is safe to discard — an agent waiting for input may be idle for
  hours.
- **Never construct manual `git branch -D` or `git branch -d` commands.**  All
  branch deletion must go through the helper's `--apply delete-local-merged-branches`
  mode.  Manually scripted deletion loops (e.g. for-loops over branch names)
  bypass the helper's safety checks and can trigger Claude Code rendering errors.
- **Never combine multiple shell operations in one `Bash` command** using `&&`,
  pipes, `$(...)`, or inline interpreters.  Issue one command per tool call.
  Compound commands can trigger Claude Code "Unhandled node type" errors.
