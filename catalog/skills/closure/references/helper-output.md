# Closure Helper Output Reference

## Branch Classifications

| Classification | Meaning |
|---|---|
| `primary` | The primary branch |
| `safe_to_delete` | Merged into primary; not in any worktree |
| `merged_checked_out` | Merged into primary; still checked out in a worktree — worktree is a cleanup candidate |
| `checked_out_in_worktree` | Not yet merged; checked out in a linked worktree — needs investigation |
| `patch_equivalent_review` | No unique patches vs primary; not in a worktree |
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
acting. The helper's `--apply delete-local-merged-branches` mode is narrower:
it may automatically remove a clean linked worktree only when the branch is
`merged_checked_out` and the liveness verdict is `stale` or `unknown`.

## Apply Mode Behavior

### `--apply delete-local-merged-branches`

Performs two kinds of cleanup:

- delete `safe_to_delete` local branches immediately
- remove a linked worktree for a `merged_checked_out` branch, then delete that
  merged branch, but only when the worktree is clean and its
  `liveness.verdict` is `stale` or `unknown`
- example: `merged_checked_out` + clean worktree + `unknown` liveness verdict
  is eligible for helper-driven removal in apply mode

This worktree-before-branch order matches the shared invariant in
`../../land-work/references/workflow-invariants.md` and avoids leaving
orphaned linked worktrees in detached `HEAD` state.

If liveness is unavailable, the worktree is dirty, or the verdict is
`confirmed_live`, `possibly_live`, or `recently_active`, the helper skips that
worktree and leaves the branch in place.

### `--apply delete-local-patch-equivalent-branches`

Force-deletes local branches classified as `patch_equivalent_review` — branches
with `unique_patch_count == 0` that are not checked out in any worktree.

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
