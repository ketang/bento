---
name: land-work
description: |
  Use when approved implementation work is ready to land and the repo permits a
  command-line landing flow. Verifies feature-branch preconditions, checks the
  landing lease deterministically, guides compare-and-set merges, then closes
  tracker work only after the landing succeeds.
recommended_model: high
---

# Land Work

## Model Guidance

Recommended model: high.

Use a high-capability model for autonomous execution. This skill has high
failure cost because it coordinates verification, lease checks, and landing.

Use this skill when implementation is complete, the branch is ready to land,
and the repo's merge policy is documented clearly enough to execute safely.

## Preconditions

- The work is committed on the feature branch.
- Required tests, lint, and build checks have passed.
- The repo allows command-line merges to its primary branch or exposes a
  documented helper for that flow.

## Deterministic Helpers

This skill includes helper scripts under `scripts/` for the risky state checks
that should not rely on ad hoc prose reconstruction:

- `python3 scripts/land-work-prepare.py` to verify the current checkout is a
  clean feature-branch worktree with something to land
- `python3 scripts/land-work-verify-lease.py --expected-sha <sha>` to verify the
  landing lease still matches the intended primary-branch ref

Run the prepare helper from the feature-branch worktree first. Use the lease
helper whenever you capture or re-check the compare-and-set merge lease.

## Workflow

1. Run the prepare helper from the feature-branch worktree:

```bash
python3 scripts/land-work-prepare.py
```

2. Confirm the current branch is the intended landing branch and that the helper
   reports a clean feature-branch checkout.
3. Re-run or verify the required quality gates for the repo.
4. Rebase onto the preferred primary-branch base reported by the helper, usually
   `origin/<primary-branch>` when available.
5. Push the feature branch with `--force-with-lease` if rebasing changed
   history.
6. Prefer the repo's documented merge helper if one exists.
7. Otherwise, perform a compare-and-set merge flow:
   - refresh the primary-branch ref you intend to lease
   - capture its SHA
   - create the merge preview the repo expects
   - run the required verification gate against that exact preview
   - re-check the lease with:

```bash
python3 scripts/land-work-verify-lease.py --expected-sha <sha>
```

   - abort if the lease changed
   - commit and push only if the lease still matches
8. After the landing succeeds, close or update the tracker item through the
   repo's tracker workflow.
9. Clean up local branch and worktree state using the repo's documented process.

## Non-Negotiable Rules

- Do not close the issue before the verified merge succeeds.
- Do not fast-forward feature branches into the primary branch unless the repo
  explicitly requires it.
- Do not merge if the leased primary-branch ref moved after verification.
- Do not land from a dirty feature-branch checkout.
- Do not change the repository's configured Git transport just because auth
  fails.

## Tracker Handoff

- If the project uses Beads, use the `beads-issue-flow` skill to close or update
  the issue after merge.
- If the project uses GitHub Issues, use the `github-issue-flow` skill.

## Direct Integration Branch Overlay

If the repo intentionally merges directly into its real integration branch,
read `references/direct-primary-branch.md` before landing. That overlay only
clarifies how to identify and target the actual integration branch; it does not
replace the safety rules or merge flow above.
