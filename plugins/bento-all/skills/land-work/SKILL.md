---
name: land-work
description: Use when approved work is ready to land via command line — verify preconditions, check the landing lease, merge, and close tracker work after landing.
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

This skill includes helper scripts under `land-work/scripts/` for the risky
state checks that should not rely on ad hoc prose reconstruction:

- `land-work/scripts/land-work-prepare.py` to verify the current checkout is a
  clean feature-branch worktree with something to land
- `land-work/scripts/land-work-verify-lease.py --expected-sha <sha>` to verify
  the landing lease still matches the intended primary-branch ref

Invoke these helpers by script path, not `python3 <script>`, so approvals stay
scoped to the script.

Run the prepare helper from the feature-branch worktree first. Use the lease
helper whenever you capture or re-check the compare-and-set merge lease.

## Command Rule

Do not generate landing as a single shell one-liner.

Never combine fetch/reset/merge/verify/push in one `Bash` command, especially
with `&&`, pipes, `$(...)`, or inline interpreters like `python3 -c`.
Compound multi-line shell commands trigger Claude Code "Unhandled node type"
rendering errors and must be avoided entirely.

Prefer:
1. the repo's landing helper, or
2. separate shell commands, one step at a time.

Run verification as its own command. Do not pipe verifier output into inline
Python.

## Workflow

1. Run the prepare helper from the feature-branch worktree:

```bash
land-work/scripts/land-work-prepare.py
```

2. Confirm the current branch is the intended landing branch and that the helper
   reports a clean feature-branch checkout.
3. Re-run or verify the required quality gates for the repo.
4. Rebase onto the preferred primary-branch base reported by the helper, usually
   `origin/<primary-branch>` when available.
   If you are preparing to merge into local `main`, rebase against local
   `main` before attempting the merge.
5. Push the feature branch with `--force-with-lease` if rebasing changed
   history.
6. Prefer the repo's documented merge helper if one exists.
7. Otherwise, perform a compare-and-set merge flow as separate commands, not
   one compound command string:
   - refresh the primary-branch ref you intend to lease
   - capture its SHA
   - create the merge preview the repo expects
   - run the required verification gate against that exact preview
   - re-check the lease with:

```bash
land-work/scripts/land-work-verify-lease.py --expected-sha <sha>
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
