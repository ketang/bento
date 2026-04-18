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
  compare-and-set merge flow.
- If the integration branch cannot be identified confidently, stop and report
  the ambiguity instead of guessing.
- Keep tracker closure, lease verification, and post-land validation exactly as
  described in the main `land-work` skill.

## Scope Boundary

This overlay does not replace `land-work`'s workflow. It only clarifies branch
selection for repositories that deliberately land into the true integration
branch instead of maintaining a separate local primary branch.

Do not use this overlay for cleanup or sync-only repos; those cases belong to
the primary-branch sync guidance in `references/primary-branch-sync.md`.
