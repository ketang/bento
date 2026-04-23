# GitHub Issues Overlay For Closure

Use this overlay only when the repo uses GitHub Issues for task tracking.

## Tracker Skill

- Use `github-issue-flow` for all issue-state changes.

## Correlation Guidance

- Cross-reference branch names, PRs, commit messages, and linked issue numbers
  when the repo's conventions make that possible.
- Record the current issue state and any active-claim signal for each
  correlated issue.
- When the core skill refers to stale tracker items, use GitHub issues whose
  work appears already landed on the repo's primary branch.

## Closeout

- Present the landing evidence first.
- If the issue appears complete and landed, hand off to `github-issue-flow`
  with a `close` recommendation.
- If the work appears superseded, abandoned, or only partially landed, hand off
  to `github-issue-flow` with an `update` or `leave open` recommendation
  instead of closing it directly from `closure`.
