# Batch Landing Mechanics

This covers the primitives `land-work` uses to land a batch of branches as
one unit, for `landing.mode: batch` repos (see
`swarm/references/landing-config.md` for that schema). It does not cover
*when* a batch is assembled or how long it lingers before running — that
queue/linger policy lives in the `swarm` skill. It also does not cover
bisecting a red batch — see `## Bisect (Out of Scope Here)` below.

## Why a Batch, Not N Serial Landings

Serial landing pays a full gate run per branch. A batch pays one full gate
run for N branches, with each branch instead diff-scope verified by its own
teammate before joining the queue (`landing.gate_scope`, the teammate
scoped-gate contract). This only works if assembling and gating the batch
tip is cheap and safe to repeat — which is why batch landing requires the
persistent `landing.integration_worktree` (see
`references/integration-worktree.md`): re-creating a scratch worktree per
batch attempt would erase the warm build-cache benefit the whole feature
exists for.

## `land-work-batch-assemble.py`

```bash
land-work/scripts/land-work-batch-assemble.py \
  --worktree <path> \
  --base-ref <leased-sha> \
  --branch <ref> [--branch <ref> ...]
```

- Validates `--worktree` is a registered worktree of the current repo.
  Refuses (`ok: false`) if it is not — this script never creates a worktree;
  resolving and validating `landing.integration_worktree` is the caller's job
  (reuse the same logic `land-work-create-preview.py` uses).
- Resets the worktree to `--base-ref` with `git reset --hard` before
  assembling anything. This clears any leftover state from a prior attempt
  — including an in-progress `MERGE_HEAD` — the same way
  `land-work-create-preview.py`'s persistent-worktree reuse path does, and
  for the same reason: nothing in this worktree's lifecycle other than its
  own merges produces tracked state that matters, so it's always safe to
  discard.
- Merges each `--branch` in the given order with `git merge --no-ff`,
  producing one real merge commit per branch (not the single-preview path's
  `--no-commit` merge). Preserving one merge commit per branch keeps
  per-issue history intact in the primary branch even though the batch lands
  as one push.
- A branch that conflicts is **evicted**: its merge is aborted
  (`git merge --abort`) before moving to the next branch, so the conflict
  never blocks the rest of the batch and the worktree is left exactly as it
  was before that branch was attempted. A branch that does not resolve to a
  commit (a name typo, a deleted ref) is evicted the same way, with its own
  reason.
- Output: `assembled` (branch, branch SHA, merge-commit SHA — in order),
  `evicted` (branch, reason, conflicting paths if applicable), `tip_sha` /
  `tip_tree` for the assembled worktree's current `HEAD` (equal to
  `base_sha` when every branch was evicted, or none were given).
- Exit 0 whenever the script itself ran without an input error (an
  unregistered worktree, a missing base ref) — a fully-evicted batch is not
  a script failure, it's a caller decision ("nothing to land this round").

## Orchestration (Land-Work Steps 1-10, Batch Variant)

See `SKILL.md`'s `## Batch Landing` section for the full step sequence:
resolve the integration worktree, capture the lease, assemble, gate once at
the tip, lease-checked push, per-branch tracker close and teardown. The push
itself is a plain `git push` (no `--force`), since the assembled tip is
always a fast-forward descendant of the leased base by construction — git's
own fast-forward rejection is a second, independent backstop behind the
explicit `land-work-verify-lease.py` re-check, not a replacement for it.

## Bisect (Out of Scope Here)

A gate failure at the assembled tip does not by itself identify which
branch caused it. The batched-swarm-landing epic's design calls for
bisecting by halves — reassembling subsets in the same warm worktree,
narrowing to the culprit branch(es), landing the green subset, and
returning culprits as rework — but that mechanism is a separate follow-up
issue, not part of `land-work-batch-assemble.py`. Until it lands, treat
every red batch as a full stop (see `SKILL.md` step 5): no partial landing,
every assembled branch returns as rework, and the failure is recorded in the
tracker.
