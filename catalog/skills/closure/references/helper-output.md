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

`closure-scan.py --apply delete-local-merged-branches` can perform two kinds
of cleanup:

- delete `safe_to_delete` local branches immediately
- remove a linked worktree for a `merged_checked_out` branch, then delete that
  merged branch, but only when the worktree is clean and its
  `liveness.verdict` is `stale` or `unknown`
- example: `merged_checked_out` + clean worktree + `unknown` liveness verdict
  is eligible for helper-driven removal in apply mode

If liveness is unavailable, the worktree is dirty, or the verdict is
`confirmed_live`, `possibly_live`, or `recently_active`, the helper skips that
worktree and leaves the branch in place.
## Recency Calculation

The helper calculates `active_seconds_since_activity` using an overnight-aware
clock that excludes 11pm–8am local time from the elapsed total. This means
activity at 10:45pm and a check at 8:15am produces ~30 active minutes, not
~9.5 hours. A worktree is considered recently active if
`active_seconds_since_activity` is under 2 hours (7200 seconds).

Last activity is the maximum of: the HEAD commit timestamp and the mtime of
any tracked file with uncommitted changes. Untracked files are excluded.
