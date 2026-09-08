# Batch Landing Mechanics

This covers the primitives `land-work` uses to land a batch of branches as
one unit, for `landing.mode: batch` repos (see
`swarm/references/landing-config.md` for that schema), including bisecting a
red batch tip (`## Bisect` below). It does not cover *when* a batch is
assembled or how long it lingers before running — that queue/linger policy
lives in the `swarm` skill.

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
  reason. A branch that resolves to a commit already an ancestor of the
  current tip (a duplicate branch in the queue, or one transitively
  contained via an earlier branch's own history) makes `git merge --no-ff`
  exit 0 with no new commit ("Already up to date"); this is also evicted
  (reason: `"already up to date: no-op merge (duplicate or already-contained
  branch)"`), not recorded as assembled — a no-op merge produces no
  merge-commit SHA of its own to report.
- Output: `assembled` (branch, branch SHA, merge-commit SHA — in order),
  `evicted` (branch, reason, conflicting paths if applicable), `tip_sha` /
  `tip_tree` for the assembled worktree's current `HEAD` (equal to
  `base_sha` when every branch was evicted, or none were given).
- Exit 0 whenever the script itself ran without an input error and the
  shared worktree stayed usable throughout — a fully-evicted batch is not a
  script failure, it's a caller decision ("nothing to land this round").
  Exit 1 with a structured `{ok: false, errors: [...]}` payload (never an
  unhandled traceback) for: an unregistered `--worktree`, a `--base-ref` that
  doesn't resolve, a registered-but-corrupted worktree (`git status` fails in
  it), foreign untracked files, a `--base-ref` that stops resolving between
  the initial check and the reset (a race with a concurrent lease refresh,
  branch cleanup, or another swarm agent — the same class of race the
  per-branch loop has always guarded against), a failed `git reset --hard`,
  or the worktree becoming unusable partway through assembly (any of the
  loop's own git calls failing after one or more branches already merged).
  The last case reports whatever was already assembled/evicted so far for
  diagnosis, with `tip_sha`/`tip_tree` left `null` since the final state
  could not be confirmed.

## Orchestration (Land-Work Steps 1-10, Batch Variant)

See `SKILL.md`'s `## Batch Landing` section for the full step sequence:
resolve the integration worktree, capture the lease, assemble, gate once at
the tip, run the project verifier once at the tip (`land-work-run-verifier.py`
— the same Non-Negotiable Rule the serial path enforces, not skipped in batch
mode), lease-checked push, per-branch tracker close and teardown. The push
itself is a plain `git push` (no `--force`), since the assembled tip is
always a fast-forward descendant of the leased base by construction — git's
own fast-forward rejection is a second, independent backstop behind the
explicit `land-work-verify-lease.py` re-check, not a replacement for it.

Steps 1-4 of the serial workflow (prepare, pre-hooks, gate baseline,
independent code review) still run once per branch, before that branch joins
the batch queue — they are part of the individual teammate's own landing
prep under the scoped-gate contract, not something batch assembly repeats
for the whole batch. Only the full-gate run and the project verifier move
from "once per branch" to "once per batch, at the tip."

## Bisect

A gate failure at the assembled tip does not by itself identify which branch
caused it. `land-work-batch-bisect.py` isolates the culprit branch(es) in the
same warm worktree, instead of the full-stop-every-branch fallback.

```bash
land-work/scripts/land-work-batch-bisect.py \
  --worktree <path> \
  --base-ref <leased-sha> \
  --gate-command <shell command> \
  --branch <ref> [--branch <ref> ...]
```

- Takes the same ordered branch list that just produced a red tip (`--branch`,
  repeated, in the same order `land-work-batch-assemble.py` was given). Does
  **not** re-gate that full list itself — the caller (SKILL.md step 4/4a)
  already confirmed it is red; re-running the same full-list gate a second
  time inside this script would just repeat that work.
- `--gate-command` is a plain shell string, run via the shell in the worktree
  for every reassembled subset (`landing.full_gate`, or a project-verifier
  invocation when it was the verifier that failed — see `SKILL.md` step 5).
- **Halving.** Splits `--branch` into two ordered halves (first half, second
  half — a branch's position never changes, only which half it lands in),
  reassembles each half fresh against `--base-ref` via
  `land-work-batch-assemble.py`, and runs `--gate-command` on it. A half that
  gates green needs no further work: every branch in it lands, untested
  individually. A half that gates red recurses the same way.
- **Bottoming out.** A red half of exactly one branch is the culprit — no
  further split is possible, and no extra gate run is needed (the half's own
  attempt already produced that verdict).
- **Non-monotonic interaction (a documented limitation).** Ordinary bisection
  assumes a single culprit that is red on its own and stays red in every
  superset — but a batch gate is not guaranteed to be monotonic: a branch can
  be green alone and only turn red combined with another one. When neither
  half of a subset already known red itself gates red, halving cannot
  localize further. This script's choice: mark the whole subset
  `ambiguous_non_monotonic` in the trail and report **every** branch in it as
  a culprit, not a guessed single one. This finds *a* red-causing subset via
  halving, not necessarily the unique minimal one — a real limitation, not a
  bug, given the failure mode isn't guaranteed monotonic.
- **Final confirmation.** Once bisection settles on `landable` (the input
  branches minus every culprit, in original order), it is reassembled fresh
  against `--base-ref` one more time and gated once more — the actual
  candidate to push, and the one piece of evidence that the survivors
  themselves combine cleanly (catching a residual non-monotonic interaction
  among them that pairwise halving alone would not).
- Output: `trail` (every subset attempted or noted, in order — each attempt
  carries its own `land-work-batch-assemble.py` payload and gate result;
  each note carries the `ambiguous_non_monotonic` explanation), `culprits`,
  `landable`, and `final` (`{assemble, gate, ok}`, or `null` when `landable`
  is empty — every branch turned out to be a culprit).
- **Reading the result.** `ok: true` at the top level means the script itself
  ran without an infra failure — it says nothing about whether anything is
  landable. Check `final`: `final.ok: true` means `landable` is the subset to
  land (normal step 6 mechanics) and `culprits` go back as rework. `final`
  being `null`, or non-null with `ok: false`, or the top-level `ok: false`
  (an infra failure: unregistered worktree, bad `--base-ref`, or the shared
  worktree becoming unusable mid-bisect, surfaced through
  `land-work-batch-assemble.py`'s own structured errors) all mean: land
  nothing, return every originally assembled branch as rework — see
  `SKILL.md` step 5 for the exact decision table.
- Record the full `trail` in the tracker issue for the batch — the acceptance
  contract this script exists to satisfy (bento-faac) is that a later reader
  can see exactly which subsets were tried, which gate failed, and which
  branch(es) were isolated, not just the final verdict.
