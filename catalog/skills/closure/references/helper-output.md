# Closure Helper Output Reference

## Branch Classifications

| Classification | Meaning |
|---|---|
| `primary` | The primary branch |
| `safe_to_delete` | Merged into primary; not in any worktree |
| `merged_checked_out` | Merged into primary; still checked out in a worktree — worktree is a cleanup candidate |
| `checked_out_in_worktree` | Not yet merged; checked out in a linked worktree — needs investigation |
| `patch_equivalent_review` | No unique patches vs primary; not in a worktree |
| `patch_equivalent_checked_out` | No unique patches vs primary; still checked out in a linked worktree — squash/rebase-landing leftover |
| `review_required` | Unmerged work not in a worktree |

## Liveness Verdicts

The `liveness.verdict` field on each worktree is one of:

| Verdict | Meaning |
|---|---|
| `confirmed_live` | A process with this worktree as CWD is running now |
| `possibly_live` | Recent activity AND a session log exists — treat as live |
| `recently_active` | Recent activity but no corroborating session log |
| `stale` | Session log exists but activity is old; no live process |
| `unknown` | No session evidence, no process — only git/file timestamps |

**Important limitation:** an agent blocked waiting for user input may show no
file or commit activity for many hours while still running. `confirmed_live`
(live process detected) is the only signal that reliably distinguishes this
case. All other verdicts are probabilistic.

For manual cleanup outside the helper's apply mode, treat `possibly_live`,
`recently_active`, and `unknown` as review-driven and ask the user before
acting. The helper's `--apply delete-local-merged-branches` mode applies a
narrower rule that is deliberately more permissive on liveness: because a
`merged_checked_out` branch is already landed on primary, timestamp-based
recency only reflects the merging agent's own just-completed activity, not a
competing live agent. The mode therefore removes a clean linked worktree for
every liveness verdict except `confirmed_live` — that is, `stale`, `unknown`,
`recently_active`, and `possibly_live` are all eligible. Only a live process
detected in the worktree blocks removal on liveness grounds (see the apply-mode
skip list below for the non-liveness gates).

## Self-Invocation Flag

Each worktree entry carries a `self_invocation` boolean. It is `true` when
the calling agent's own process tree (the helper's PPID chain, walked via
`/proc`) has a cwd inside that worktree. This identifies the worktree the
agent is currently *living in*, distinguishing it from sibling worktrees that
merely happen to be recently active.

Self-invocation takes precedence over every other apply-mode skip reason. The
helper emits the skip reason `self-invocation: helper invoked from inside
this worktree; use land-work for own-work cleanup, not closure` so the
caller is redirected to the right tool instead of seeing a generic liveness
refusal.

On non-Linux platforms or when `/proc` access is restricted, the helper
falls back to checking the helper's own startup cwd; the flag may be
`false` for ancestors that cannot be inspected.

## Apply Mode Behavior

### `--apply delete-local-merged-branches`

Performs two kinds of cleanup:

- delete `safe_to_delete` local branches immediately
- remove a linked worktree for a `merged_checked_out` branch, then delete that
  merged branch, when the worktree is clean and its `liveness.verdict` is
  anything other than `confirmed_live`
- example: `merged_checked_out` + clean worktree + `unknown`, `stale`,
  `recently_active`, or `possibly_live` liveness verdict is eligible for
  helper-driven removal in apply mode

This worktree-before-branch order matches the shared invariant in
`../../land-work/references/workflow-invariants.md` and avoids leaving
orphaned linked worktrees in detached `HEAD` state.

The helper skips a `merged_checked_out` worktree and leaves the branch in place
when any of these gates fire (in this order):

- `self_invocation` is true — use `land-work` for own-work cleanup, not closure
- the worktree is the current checkout
- the worktree is detached
- the worktree has uncommitted changes (dirty tree)
- an in-flight launch-work checkpoint is present (`checkpoint` set and not
  `ready-to-land`)
- liveness assessment is unavailable (e.g. `--no-liveness`)
- the liveness verdict is `confirmed_live`

Note that `possibly_live` and `recently_active` do **not** block removal here:
for an already-merged branch the recency is the merging agent's own activity,
so only a `confirmed_live` process is treated as a competing agent.

### `--apply delete-local-patch-equivalent-branches`

Force-deletes local branches with `unique_patch_count == 0` in both
patch-equivalent classifications:

- `patch_equivalent_review` — not checked out in any worktree; the branch is
  force-deleted directly.
- `patch_equivalent_checked_out` — still checked out in a linked worktree. The
  helper first removes the worktree using the same safety gates as
  `merged_checked_out` (self-invocation, current checkout, detached, dirty
  tree, in-flight launch-work checkpoint, liveness unavailable, or
  `confirmed_live` all block removal), then force-deletes the checked-out
  branch. If any gate blocks the worktree, the branch is left in place.

These branches were landed via rebase or squash merge, so they are not reachable
ancestors of the primary branch and `git branch -d` would refuse them. The
helper uses `git branch -D`. This is safe because `unique_patch_count == 0`
(verified via `git cherry`) confirms no content unique to the branch is missing
from primary.

The two apply modes are independent. Run both in sequence to clear all
no-content local branches:

```bash
closure/scripts/closure-scan.py --apply delete-local-merged-branches
closure/scripts/closure-scan.py --apply delete-local-patch-equivalent-branches
```
## Branch Correlation (`--correlate-branches`)

Off by default. When set, each `review_required` branch entry carries a
`correlation` block:

| Field | Source |
|---|---|
| `issue_id` | `--issue-pattern` regex on branch name; cleared if tracker lookup does not recognize the candidate |
| `cherry_unique_count`, `cherry_equivalent_count` | `git cherry <primary> <branch>` `+`/`-` line counts |
| `main_commits_referencing_issue` | `git log <primary> --grep=<id> --fixed-strings --since=<merge-base-date> --format=%h` |
| `tracker_status` | tracker shim (`bd show`, `gh issue view`, JIRA REST); `null` when tracker is `none` or lookup fails |
| `merge_base_age_days` | days between `git merge-base` commit time and now |
| `divergence_ahead`, `divergence_behind` | `git rev-list --left-right --count <primary>...<branch>` |

Tracker auto-detection precedence: `.beads/` → beads; else JIRA env vars
present → jira; else `.github/` + `gh` CLI available → gh; else `none`.
Override with `--tracker {beads,gh,jira,none}`.

Issue-id default patterns: beads `([a-z]+-[a-z0-9]+)`, jira `([A-Z]+-[0-9]+)`,
gh `#?([0-9]+)`. Override with `--issue-pattern`.

Correlation produces signals only — no verdict, and no new `--apply` mode.
Heuristic deletion belongs to the agent + user, not the helper.

## Recency Calculation

The helper calculates `active_seconds_since_activity` using an overnight-aware
clock that excludes 11pm–8am local time from the elapsed total. This means
activity at 10:45pm and a check at 8:15am produces ~30 active minutes, not
~9.5 hours. A worktree is considered recently active if
`active_seconds_since_activity` is under 2 hours (7200 seconds).

Last activity is the maximum of: the HEAD commit timestamp and the mtime of
any tracked file with uncommitted changes. Untracked files are excluded.
