# Direct Primary Branch Landing Overlay

Use this overlay only when the repo intentionally merges implementation work
directly into the real integration branch.

Treat `<integration-branch>` as the branch the repository actually uses for
integration. Do not assume `main` unless repo config or remote defaults confirm
it.

## Policy

- Detect the integration branch from repo-specific configuration or the remote
  default branch before rebasing or merging.
- Land into that branch directly using the normal `land-work` safety checks and
  compare-and-set merge flow. When `land-work-prepare.py` reports
  `primary_local_vs_remote` as `ahead` or `diverged` for the primary
  checkout's local `<integration-branch>`, use the push-from-preview route
  (SKILL.md step 8) exactly as for `main`/`master`: commit the merge in the
  preview worktree, push straight from there with
  `git push origin HEAD:refs/heads/<integration-branch>`, then sync the
  primary with `git fetch origin` + `git merge --ff-only
  origin/<integration-branch>`. This is the standard route for that
  diagnostic regardless of which branch name is the real integration branch.
  `equal`, `behind`, or `null` (no remote-tracking ref exists to compare
  against) all take the normal merge-in-the-primary route instead.
- If the integration branch cannot be identified confidently, stop and report
  the ambiguity instead of guessing.
- Keep tracker closure, lease verification, and post-land validation exactly as
  described in the main `land-work` skill.

## Scope Boundary

This overlay does not replace `land-work`'s workflow. It only clarifies branch
selection for repositories that deliberately land into the true integration
branch instead of maintaining a separate local primary branch.

Do not use this overlay for cleanup or sync-only repos; those cases belong to
the primary-branch sync guidance in
`../../closure/references/primary-branch-sync.md`.
