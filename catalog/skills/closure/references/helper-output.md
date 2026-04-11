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
case. All other verdicts are probabilistic. When `verdict` is `possibly_live`,
`recently_active`, or `unknown`, present the evidence and ask the user rather
than acting unilaterally.

## Recency Calculation

The helper calculates `active_seconds_since_activity` using an overnight-aware
clock that excludes 11pm–8am local time from the elapsed total. This means
activity at 10:45pm and a check at 8:15am produces ~30 active minutes, not
~9.5 hours. A worktree is considered recently active if
`active_seconds_since_activity` is under 2 hours (7200 seconds).

Last activity is the maximum of: the HEAD commit timestamp and the mtime of
any tracked file with uncommitted changes. Untracked files are excluded.
