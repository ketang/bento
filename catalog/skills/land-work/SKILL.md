---
name: land-work
description: Hard trigger — invoke after finishing your own approved feature-branch work to merge it, close tracker work, and tear down the feature branch and its linked worktree afterward. This is the routine post-merge cleanup path for the agent that did the work; do not use closure for that.
---

# Land Work

## Model Guidance

Recommended model: high.

Use a high-capability model for autonomous execution. This skill has high
failure cost because it coordinates verification, lease checks, and landing.

Use this skill when implementation is complete, the branch is ready to land,
and the repo's merge policy is documented clearly enough to execute safely.

Open `references/workflow-invariants.md` before landing when you need the
shared rules for primary-branch terminology, tracker mutation timing, or
linked-worktree cleanup order.

## Preconditions

- The work is committed on the feature branch.
- Required tests, lint, and build checks have passed.
- The repo allows command-line merges to its primary branch or exposes a
  documented helper for that flow.

## Deterministic Helpers

This skill includes helper scripts under `land-work/scripts/` for the risky
state checks that should not rely on ad hoc prose reconstruction:

- `land-work/scripts/land.py` (bento-rdtn.14) orchestrates the whole
  fetch → create-preview → verify → lease-recheck → merge+push → cleanup →
  verify-landing sequence as one command, run from the feature-branch
  worktree after step 1's prepare/pre-hooks/gate-baseline/code-review steps.
  Prefer it over issuing step 8's individual commands by hand — see step 7a.
- `land-work/scripts/land-work-prepare.py` to verify the current checkout is a
  clean feature-branch worktree with something to land and, when requested,
  that it is not stale relative to the primary branch. Also reports the
  *primary checkout's own* state — `primary_bare`, `primary_dirty`, and
  `primary_local_vs_remote` (`ahead`/`behind`/`diverged`/`equal`/`null` when no
  remote-tracking ref exists) — and fails closed on a bare or dirty primary.
  `ahead`/`diverged` is not itself a failure: it means the primary checkout
  cannot receive a normal local merge right now (its local branch already has
  commits the leased origin ref doesn't), so land from the preview instead —
  see step 8's push-from-preview route below.
- `land-work/scripts/land-work-create-preview.py` to materialize the exact
  merge candidate from the leased primary-branch base into a preview checkout
  (and `--cleanup --preview-dir <path>` to remove that registered worktree
  once verification finishes). Refuses to start a new scratch preview while a
  `land-work-preview-*` worktree from an earlier, uncleaned landing attempt is
  still registered — pass `--allow-existing` to override. When the repo's
  `swarm-config.json` declares
  `landing.integration_worktree`, the preview materializes there instead of a
  scratch `/tmp` directory, reusing build caches across landings — see
  `land-work/references/integration-worktree.md`. `--cleanup` is a safe no-op
  against that configured path; it never removes it.
- `land-work/scripts/land-work-run-verifier.py` to run the repo's configured
  project verifier against the exact merge preview and fail closed unless every
  landed path is covered. It never equates a zero-check verifier result with
  verified evidence: a real diff with no matching selected check stops the
  landing. Persists the verifier command's raw stdout+stderr to
  `<candidate>/.land-work/verifier.log` (or `--log <path>`) and reports a
  `verifier_status` of `passed`, `failed`, `killed`, or `timeout` — `killed`
  means no usable result was ever produced (signal death, unparseable output),
  which is worth one retry after inspecting the log; `failed` means a real,
  valid result reported a real failure, which is not. See
  `references/project-verifier.md` for the manifest contract. If
  no manifest exists anywhere in the discovery chain, land-work invokes
  `wire-land-verifier` inline rather than deferring the fix to a later,
  separately remembered step — see the missing-manifest exception in step 8.
- `land-work/scripts/land-work-verify-lease.py --expected-sha <sha>` to verify
  the landing lease still matches the intended primary-branch ref
- `land-work/scripts/land-work-verify-landing.py --expected-tree <tree>` to
  verify the landed primary-branch ref still matches the verified candidate;
  add `--preview-dir <path>` for a scratch preview to also fail if that
  worktree is still registered (i.e. cleanup was skipped)
- `land-work/scripts/land-work-root-hygiene.py` to audit the primary checkout
  root after landing for untracked files not covered by `.gitignore` (step 9a)
- `land-work/scripts/land-work-batch-assemble.py` to merge an ordered list of
  branches into one worktree as a chain of explicit merge commits, for
  `landing.mode: batch` repos only — see `## Batch Landing` below and
  `references/batch-landing.md`
- `land-work/scripts/land-work-batch-bisect.py` to isolate the culprit
  branch(es) in a red batch tip by halving, for `landing.mode: batch` repos
  only — see `## Batch Landing` step 5 and `references/batch-landing.md`

Invoke these helpers by script path, not `python3 <script>`, so approvals stay
scoped to the script. Resolve each helper path relative to this `SKILL.md`
file: if you opened `/.../skills/land-work/SKILL.md`, run
`/.../skills/land-work/scripts/land-work-prepare.py`. Do not search the whole
plugin cache to rediscover the helper path.

Run the prepare helper from the feature-branch worktree first. Use the preview
helper to create the exact candidate you will verify, the lease helper whenever
you capture or re-check the compare-and-set merge lease, and the landing
verifier after merge before closing tracker work.

## Command Rule

Do not generate landing as a single shell one-liner.

Never combine fetch/reset/merge/verify/push in one shell command, especially
with `&&`, pipes, `$(...)`, or inline interpreters like `python3 -c`.

Prefer:
1. the repo's landing helper, or
2. separate shell commands, one step at a time.

Run verification as its own command. Do not pipe verifier output into inline
Python.

For Codex, avoid shell pipelines for discovery as well. Prefer one direct
command at a time, such as `git worktree list --porcelain` or the absolute
helper path beside this skill, so sandbox approvals stay narrowly scoped.

## Workflow

1. Run the prepare helper from the feature-branch worktree:

```bash
land-work/scripts/land-work-prepare.py --require-up-to-date
```

2. Confirm the current branch is the intended landing branch and that the helper
   reports a clean feature-branch checkout.
2a. Read `../launch-work/references/project-hook-scripts.md` and
    `../launch-work/references/project-hook-skills.md`. Run the **`pre`**
    hook scripts before creating or verifying the merge preview, rebasing, or
    merging:

    ```bash
    ../launch-work/scripts/run-lifecycle-extensions.py run-hooks \
      --repo-root <repo-root> \
      --skill land-work \
      --position pre \
      --branch <feature-branch> \
      --worktree <feature-worktree> \
      --base-ref <primary-branch> \
      --base-sha <leased-sha> \
      --head-sha $(git rev-parse HEAD) \
      --runtime <runtime>
    ```

    Then discover and apply `pre` hook skills:

    ```bash
    ../launch-work/scripts/run-lifecycle-extensions.py discover \
      --repo-root <repo-root> \
      --skill land-work \
      --kind hook-skills \
      --position pre
    ```

    Use `claude`, `codex`, or `unknown` for `<runtime>` to match the current
    agent runtime. Read each listed file in order and apply. If a hook script
    exits non-zero or a `## Stop conditions` predicate matches, halt; the merge
    has not started.
2b. If a tracked `.launch-work/log.md` exists on the branch, remove it in a
    normal commit before review.
2c. **Gate evidence — discover and baseline.** Read
    `references/gate-evidence.md` and follow it. Discover the repo's gate suite
    and confirm the primary branch is green before landing (halt on a
    pre-existing red base). If no suite is discoverable after checking every
    listed surface, record that explicitly; never claim green.
3. Treat any verification that ran before a rebase, merge, cherry-pick, or
   manual conflict resolution as stale evidence only. It does not authorize a
   landing after the candidate changes.
4. Run an independent code review of the feature diff before merging.

   **Why independent:** the reviewer must see only the code and its stated
   purpose — not the implementation session's reasoning. A reviewer who
   absorbed your rationale cannot catch the gaps your rationale missed.

   Compute the feature-only diff base (excludes any primary-branch commits
   merged in during development):

   ```bash
   BASE_SHA=$(git merge-base HEAD origin/<primary-branch>)
   HEAD_SHA=$(git rev-parse HEAD)
   ```

   **Preferred — built-in review skill:**

   *Claude Code:* invoke the `code-review` skill, targeting the range
   `$BASE_SHA..$HEAD_SHA`. Prepend a one- or two-sentence purpose statement
   drawn from the tracker issue title and description — not from your session
   context.

   *Codex:* use the equivalent built-in review command.

   **Fallback — explicit subagent:**

   If no built-in skill is available, dispatch a subagent with only this
   prompt — no additional session context:

   ```
   You are a senior code reviewer examining this change for the first time.
   Evaluate the code on its own merits; do not ask about implementation
   rationale.

   Purpose: {one or two sentences from the tracker issue title and description}

   Review the diff:
     git diff {BASE_SHA}..{HEAD_SHA}

   Criteria, in priority order:
   1. Correctness — does it do what the purpose states? Edge cases handled?
   2. Duplication — before concluding a new helper is warranted, search the
      codebase for existing utilities that already do the same thing. Flag
      any logic that duplicates something elsewhere.
   3. Maintainability — clear naming, single responsibility, no unnecessary
      abstraction, no surprising side effects. Would a reader unfamiliar with
      this session understand it?
   4. Safety — error handling at system boundaries, no silent failures?
   5. Fit — consistent with surrounding code style and conventions?

   For each issue: file:line, what is wrong, why it matters, how to fix it.
   Categorize as Critical / Important / Minor.
   Verdict: Ready to merge | Merge with fixes | Do not merge.
   ```

   **Acting on findings:**
   - Fix Critical and Important issues before rebasing or merging.
   - Create tracker follow-up items for Minor issues that are real but
     non-blocking.
   - If the reviewer is wrong, push back with technical reasoning — do not
     silently discard valid findings.
   - A "Merge with fixes" verdict requires the fixes to be committed before
     proceeding to the next step.

   Also check design concerns automated tools miss: optional capabilities that
   crash instead of degrading on missing resources; committed artifacts
   diverging from workspace state (see `references/artifact-verification.md`
   when binary or LFS files are in the diff); container build inputs that
   differ between local and remote platforms.
5. Rebase onto the preferred primary-branch base reported by the helper, usually
   `origin/<primary-branch>` when available.
   If you are preparing to merge into local `main`, rebase against local
   `main` before attempting the merge.
   If the rebase or preview merge requires manual conflict resolution, require
   a fresh run of the discovered gate suite (step 2c) and an explicit review
   checkpoint on the resolved candidate before landing.
6. Push the feature branch with `--force-with-lease` if rebasing changed
   history.
6a. **Gate requirement (both merge paths).** Before completing the merge —
    whether via the step 7 helper or the step 8 compare-and-set flow — the
    discovered gate suite (step 2c) must pass on the exact merge candidate.
    Capture each gate command and its exit status. Merge only on all-green or a
    waiver recorded per `references/gate-evidence.md`. If the merge helper
    cannot run against the exact candidate, use the step 8 flow instead.
7. Prefer the repo's documented merge helper if one exists only when it can
   prove or preserve the same exact candidate you verified. If the helper
   cannot expose equivalent candidate evidence, fall back to the explicit
   compare-and-set flow below.
7a. **Prefer the orchestrating driver for step 8 as a whole (bento-rdtn.14).**
    Before issuing the compare-and-set flow's individual commands by hand, run:

```bash
land-work/scripts/land.py --runtime <runtime>
```

    from the feature-branch worktree. It runs fetch → create-preview →
    run-verifier → verify-lease (recheck) → merge+push → cleanup →
    verify-landing as one sequence, choosing the normal or push-from-preview
    route itself from step 1's `primary_local_vs_remote` diagnostic, printing
    one line per step (name, status, seconds, and cached/executed for the
    verify step), and always removing the preview worktree in a `finally` —
    including on SIGINT/SIGTERM, and aborting an in-progress primary-checkout
    merge on interrupt. It stops at the first failed step and reports the
    step name, the error, and (for a verifier failure) the raw log path in
    its final JSON. Exit 0 means every step in the sequence succeeded,
    including verify-landing; proceed straight to step 9. A nonzero exit
    means the failed step's own diagnostics are the source of truth — fix
    that specific problem and re-run `land.py` from the top; do not fall
    back to the manual flow below just because one run failed.

    Use the manual compare-and-set flow in step 8 instead only when
    `land.py` is missing from this checkout (an older bento install) or you
    deliberately need to intervene between its steps (e.g. a `landing.mode:
    batch` repo, which `land.py` does not handle — see `## Batch Landing`
    below).
8. Otherwise, perform a compare-and-set merge flow as separate commands, not
   one compound command string:
   - refresh the primary-branch ref you intend to lease
   - capture its SHA
   - create the merge preview the repo expects with:

```bash
land-work/scripts/land-work-create-preview.py --base-ref <sha>
```

   - run the project verifier against that exact preview, using the preview
     directory the previous helper reported as the candidate. Run this after
     preview creation and before the lease re-check and merge:

```bash
land-work/scripts/land-work-run-verifier.py \
  --repo-root <repo-root> \
  --candidate <preview-dir> \
  --base-sha <leased-sha> \
  --head-sha <feature-head-sha> \
  --runtime <runtime>
```

     A nonzero exit stops the landing: the verifier has a nonempty relevant
     diff that no passed selected check covers, the manifest is missing or
     invalid, or the verifier command failed, timed out, or returned an
     unusable result. Exit 0 means every landed path is covered or exactly
     exempted.

     The diagnostics JSON's `verifier_status` distinguishes four outcomes —
     `passed`, `failed`, `killed`, `timeout` — and `verifier_log` names where
     the command's raw stdout+stderr was persisted (default
     `<preview-dir>/.land-work/verifier.log`, overridable with `--log`).
     `failed` means the verifier command actually produced a valid,
     schema-matching result and that result reports a real failure (a check
     didn't pass, a nonempty relevant diff had zero passed checks, etc.) — fix
     the underlying problem and re-run; never blindly retry a `failed` run
     hoping it passes on its own. `killed` means no such usable result was
     ever produced (the child died by signal, exited with no parseable
     output, or the parsed JSON was malformed) — this is exactly the
     "produced no signal" case that is indistinguishable from an externally
     killed process, so inspect `verifier_log` (or the `verifier_log_tail`
     lines already in the diagnostics) for what actually happened, and it is
     reasonable to rerun once before concluding the gate itself is broken.
     `timeout` is this helper's own `--timeout` kill, not an external one; the
     command is likely too slow for the given budget, not broken.

     **Missing-manifest exception.** If the reported error is specifically "no
     verifier manifest configured" (no manifest found anywhere in the
     discovery chain, with a nonempty relevant diff), do not just halt and
     tell the user to run `wire-land-verifier` separately later. Verifier
     setup is per-project and easy to forget until a landing is already
     blocked on it, so land-work triggers the on-ramp itself instead of
     deferring to a remembered manual step:
     8i. Remove the current preview worktree (the cleanup command below) — it
        is stale once the feature branch gains a new commit.
     8ii. Return to the feature-branch worktree and invoke the
        `wire-land-verifier` skill there. It still requires explicit
        repo-owner confirmation of the real gate command and an explicit
        go-ahead before `apply` installs anything — auto-invoking it here
        shortens the path to that confirmation prompt, it does not skip it.
     8iii. Once `wire-land-verifier` commits the manifest and wrapper on the
        feature branch, re-run this compare-and-set flow from the preview
        step (step 8) against the updated feature HEAD: recreate the preview,
        re-run the project verifier, and satisfy the gate requirement (step
        6a) again on the new exact candidate.
     8iv. If the repo owner declines to confirm a real gate command, or
        `wire-land-verifier` cannot produce a passing draft, stop; this is a
        normal landing failure, not a missing-manifest retry.

     Any other nonzero exit (a real gate failure, an invalid existing
     manifest, or a verifier command error) is a normal landing failure: do
     not proceed to the lease check or merge; remove the preview worktree (the
     cleanup command below) before stopping.
   - satisfy the gate requirement (step 6a) against that exact preview only; do
     not reuse pre-rebase or pre-conflict results
   - re-check the lease with:

```bash
land-work/scripts/land-work-verify-lease.py --expected-sha <sha>
```

   - abort if the lease changed — and before stopping, remove the preview
     worktree (the cleanup command below); an aborted landing must not leave
     its scratch worktree registered
   - commit and push only if the lease still matches, using one of two routes
     depending on what `land-work-prepare.py`'s `primary_local_vs_remote`
     reported at step 1 (concurrent sessions can also move the primary
     between then and now, so re-check if time has passed):
     - **Normal route** (`equal`, `behind`, or `null` — the primary
       checkout's local branch is not ahead of the leased origin ref, or no
       remote-tracking ref exists to compare against): merge in the primary
       checkout as usual, then push it.
     - **Push-from-preview route** (`ahead` or `diverged` — the primary
       checkout's local branch already has commits the leased origin ref
       doesn't, so a normal merge-then-push from the primary would either
       silently include those extra commits in the landing or fail outright).
       No flag selects this; it is the standard route for this diagnostic, not
       a workaround. Do not touch the primary checkout's branch at all:
       1. Finish the merge preview already started with `--no-commit` into a
          real commit, in the preview worktree: `git commit`.
       2. Push straight from the preview worktree to the leased remote,
          non-force: `git push origin HEAD:refs/heads/<primary-branch>`
          (`origin` is the same remote `land-work-verify-lease.py` leases
          against).
       3. Sync the primary checkout the safe way — fetch, then fast-forward
          only: `git fetch origin` then
          `git merge --ff-only origin/<primary-branch>` in the primary
          checkout. `--ff-only` refuses instead of creating a surprise merge
          commit if the primary gained yet another local commit in the
          meantime.
       See `references/direct-primary-branch.md` for the same route applied
       when the repo's real integration branch isn't `main`/`master`.
   - **Always** remove the preview worktree once you are done with it, on every
     exit path — verified landing, aborted lease, or any error after the
     preview was created. It is a registered git worktree and otherwise
     accumulates under `/tmp` until a manual closure sweep removes it — unless
     the preview payload reported `"persistent_worktree": true` (the repo
     declares `landing.integration_worktree`; see
     `land-work/references/integration-worktree.md`), in which case skip this
     step entirely: the worktree is meant to persist across landings and
     `--cleanup` against it is a safe no-op anyway. Do this **before**
     verify-landing below, not after: verify-landing itself checks that the
     scratch preview is no longer registered, so a skipped cleanup fails
     verify-landing instead of leaking a preview worktree silently.

```bash
land-work/scripts/land-work-create-preview.py --cleanup --preview-dir <preview-dir>
```

     `land-work-create-preview.py` already removes its own worktree when the
     preview itself fails (merge conflict or error), reporting
     `"preview_cleaned_up": true` — except for a persistent
     `landing.integration_worktree`, which a failed preview leaves clean
     (merge aborted) rather than removed, for reuse by the next landing
     attempt. The explicit cleanup above covers the success and abort paths
     for a scratch preview, which the helper cannot clean for you because you
     still need the preview to verify the landing.
   - verify the landed primary-branch ref still matches the verified preview,
     and — for a scratch preview (not a persistent
     `landing.integration_worktree`) — that its worktree is no longer
     registered, by passing `--preview-dir`. `land-work-create-preview.py`
     also refuses to start a new preview while a leftover
     `land-work-preview-*` worktree is still registered from an earlier,
     uncleaned landing attempt (pass `--allow-existing` to override), so an
     unremoved preview surfaces immediately rather than silently accumulating
     under `/tmp`:

```bash
land-work/scripts/land-work-verify-landing.py --expected-tree <tree> --preview-dir <preview-dir>
```
8a. Run the **`post`** hook scripts in **advisory mode** (the merge has
    already succeeded; abort cannot reverse it):

    ```bash
    ../launch-work/scripts/run-lifecycle-extensions.py run-hooks \
      --repo-root <repo-root> \
      --skill land-work \
      --position post \
      --advisory \
      --branch <feature-branch> \
      --worktree <feature-worktree> \
      --base-ref <primary-branch> \
      --base-sha <new-base-sha> \
      --merge-sha $(git rev-parse <primary-branch>) \
      --landed 1 \
      --runtime <runtime>
    ```

    Then discover and apply `post` hook skills (also advisory):

    ```bash
    ../launch-work/scripts/run-lifecycle-extensions.py discover \
      --repo-root <repo-root> \
      --skill land-work \
      --kind hook-skills \
      --position post
    ```

    Use `claude`, `codex`, or `unknown` for `<runtime>` to match the current
    agent runtime. Surface any non-zero hook script exits or matched `## Stop
    conditions` predicates to the user as warnings; do not unwind the merge,
    do not block tracker mutations.
9. After the landing succeeds, close or update the tracker item through the
   repo's tracker workflow. Follow `references/workflow-invariants.md`:
   mutate tracker state only after the work is verified as landed on the
   detected primary branch. The closure note must carry the gate evidence
   (step 6a) — each gate command and its exit status, or the recorded waiver, or
   "no gate suite discovered" when none ran. Evidence, not the bare assertion
   that "tests pass". To catch a forgotten close later (a stale claim on a
   landed branch), re-run `land-work-verify-landing.py --issue auto` (or an
   explicit id) from that branch's worktree — it warns, without changing the
   exit code, if the branch's tracker issue is not `closed`/`CLOSED`, naming
   the exact `bd close ...`/`gh issue close ...` command.
9a. Audit the primary checkout root for stray untracked files. The prepare
    helper only checks the feature worktree, so junk in the primary root
    (stray scratch files, accidental writes) survives every landing. Run the
    hygiene helper, pointing at the primary checkout root:

    ```bash
    land-work/scripts/land-work-root-hygiene.py
    ```

    It runs `git status --porcelain=v1 --untracked-files=all` in the primary
    checkout and reports `untracked_paths`: untracked files not covered by
    `.gitignore` (ignored files are omitted, so a clean root adds no noise).
    The check is advisory — the merge is already done. If `clean` is false,
    surface each path to the user and ask them to delete it or add it to
    `.gitignore`. Never auto-delete.
9b. Before removing the feature worktree, account for every untracked file
    created or touched during this task. Run, in the feature worktree:

    ```bash
    git status --porcelain=v1 --untracked-files=all
    ```

    This is a checklist gate, not a silent auto-delete: resolve each listed
    untracked path to exactly one of three outcomes before proceeding to
    cleanup —
    - **committed** — it belongs in the landed change (and was already part of
      the verified candidate), or
    - **gitignored** — it is expected local-only state covered by `.gitignore`,
      or
    - **deleted** — it is scratch residue with no lasting value.

    Plan, log, and handoff files for the landed work (for example
    `.launch-work/log.md`, plan scratch, or handoff notes) must **not** remain
    untracked into cleanup — commit them if they are part of the record, or
    delete them. A leftover untracked file is not an acceptable end state; if
    you cannot decide an outcome for a path, stop and ask the user rather than
    removing the worktree over unaccounted residue.
10. Clean up the merged feature branch and its linked worktree directly. This
    is the routine post-landing path for the agent that just landed its own
    work. Return to the repo root on the primary branch first (you cannot
    remove the worktree you are standing in), then run, in order, as separate
    commands:

    ```bash
    git worktree remove <worktree-path>
    ```

    ```bash
    git branch -d <feature-branch>
    ```

    The ordering rule from `references/workflow-invariants.md` is structural:
    remove the linked worktree before deleting the branch. `git branch -d`
    (lowercase `-d`) refuses to delete an unmerged branch, so it is the safe
    default after a verified merge.

    Reach for `closure` only as a fallback for stale or ambiguous leftovers
    (a worktree that was not yours, a branch whose merge state is unclear, or
    direct cleanup that failed for a reason you cannot explain). For your own
    just-landed branch, do not invoke
    `closure/scripts/closure-scan.py --target-branch <name> --apply delete-local-merged-branches` —
    closure is a GC pass over other agents' leftovers, and its liveness gate
    is not designed to protect your own worktree. Once you have stepped out of
    it, `self_invocation` is false and `recently_active`/`possibly_live` do not
    block removal.

## Batch Landing

Everything above is the serial path: one branch, one gate run, one merge.
Serial-mode repos (no `swarm-config.json`, or `landing.mode` absent/`serial`)
are unaffected by this section — its mechanics never run for them.

For a repo whose `swarm-config.json` declares `landing.mode: batch` (see
`swarm/references/landing-config.md` for the schema and its fail-safe
validation), swarm's queue/linger policy assembles a batch of ready branches
and calls into land-work to land them as one unit, replacing steps 5-10 above
with the steps below. Steps 1-4 above (prepare, pre-hooks, gate baseline,
independent code review) are **not** skipped in batch mode — they still run
once per branch, before that branch is queued, as part of the teammate's own
landing prep under the scoped-gate contract (a diff-scoped code review and
`landing.gate_scope` run against that branch's own diff, not the whole
batch). What changes in batch mode is only what happens after a branch is
ready: instead of landing it alone under its own full gate, it joins the
queue and lands as part of the next assembled batch, gated once at the tip.

1. **Resolve the worktree.** Batch landing always uses the repo's
   `landing.integration_worktree` (required for `mode: batch` to be usable at
   all in practice, though `swarm-discover.py` does not enforce that — an
   absent worktree just means no warm reuse). Validate it using the same
   registered/not-foreign-dirty checks `land-work-create-preview.py` applies
   for a single landing (see `references/integration-worktree.md`), but with
   a deliberately different outcome on failure: `land-work-create-preview.py`
   falls back to a scratch `/tmp` worktree and proceeds, while batch mode
   halts instead of guessing — a mid-batch fallback to scratch would defeat
   the point of assembling N branches into one shared, warm worktree.
2. **Capture the lease.** Refresh and capture the primary-branch ref SHA, the
   same compare-and-set base every branch in the batch will assemble against.
3. **Assemble.**

   ```bash
   land-work/scripts/land-work-batch-assemble.py \
     --worktree <integration-worktree> \
     --base-ref <leased-sha> \
     --branch <branch-1> --branch <branch-2> ...
   ```

   This resets the worktree to the leased base, then merges each branch in
   order with `--no-ff`, one merge commit per branch. A branch that conflicts
   is evicted (its merge is aborted; the worktree is left exactly as it was
   before that branch was attempted) and assembly continues with the rest —
   report evicted branches back to their teammates as rework, do not retry
   them in this batch. If every branch is evicted, there is nothing to land;
   stop here.
4. **Gate once, at the tip.** Run `landing.full_gate` in the assembled
   worktree (the tip of the merge-commit chain `land-work-batch-assemble.py`
   just produced). This is the single full-gate run for the whole batch —
   individual branches were only diff-scope verified by their teammates
   (`landing.gate_scope`), per the teammate-scoped-gate contract.
4a. **Project verifier, at the tip.** The Non-Negotiable Rule "Do not merge
    unless `land-work-run-verifier.py` exits 0 on the exact merge preview" is
    not scoped to the serial path — run it here too, against the assembled
    worktree as the candidate and the batch tip as the head:

    ```bash
    land-work/scripts/land-work-run-verifier.py \
      --repo-root <repo-root> \
      --candidate <integration-worktree> \
      --base-sha <leased-sha> \
      --head-sha <tip-sha-from-step-3> \
      --runtime <runtime>
    ```

    A nonzero exit is the same landing failure it is on the serial path
    (missing/invalid manifest, zero selected checks against a real diff, or a
    verifier command error) — do not proceed to the gate requirement, the
    lease re-check, or the push.
5. **Red batch → bisect.** A gate or verifier failure at the tip does not by
   itself identify which assembled branch caused it. Bisect in the same warm
   worktree instead of a full stop:

   ```bash
   land-work/scripts/land-work-batch-bisect.py \
     --worktree <integration-worktree> \
     --base-ref <leased-sha> \
     --gate-command <landing.full_gate command> \
     --branch <branch-1> --branch <branch-2> ...
   ```

   Pass the same ordered branch list step 3 assembled (the one whose tip just
   gated or verified red). The script splits it in half, reassembles each
   half against the leased base via `land-work-batch-assemble.py`, runs
   `--gate-command` on each half, and recurses into whichever half(ves) are
   still red — bottoming out at a single branch (the culprit) or, when
   neither half of a red parent gates red alone, at an
   `ambiguous_non_monotonic` note that attributes the whole parent subset (a
   branch that is only red in combination with another one; see
   `references/batch-landing.md`'s `## Bisect` section for why plain halving
   cannot localize that case further). It then reassembles the surviving
   `landable` subset once more and gates it a final time to confirm.

   - If `final.ok` is `true`: `landable` is the subset to land (step 6, same
     mechanics as a clean batch). `culprits` are returned as rework. Record
     the full `trail` (every subset tried, its gate result, and which
     branch(es) were isolated) in the tracker issue for the batch.
   - If `final` is `null` (every input branch turned out to be a culprit, so
     there was nothing to reassemble/confirm — e.g. two branches that are
     each independently broken): the script itself still reports `ok: true`
     (it did its job correctly), but `landable` is empty. Treat this exactly
     like the old full-stop path — return **every** originally assembled
     branch as rework, and record the trail in the tracker. Do not reuse the
     integration worktree for the next landing round without resetting it
     first: it is left checked out at whatever the last bisection attempt
     assembled, not at a clean base.
   - If `final.ok` is `false` (the confirmation gate on `landable` itself
     failed — a residual non-monotonic interaction among the survivors that
     pairwise halving did not catch) or the script itself reports `ok: false`
     (an infra failure: unregistered worktree, bad base-ref, a duplicate
     `--branch`, or the shared worktree becoming unusable mid-bisect,
     including a branch silently evicted during a subset's reassembly):
     treat this exactly like the old full-stop path — do not land any part
     of the batch, return **every** originally assembled branch as rework
     (not just `culprits`), and record the failure and trail in the tracker.
   - If the project verifier (step 4a), not the gate, is what failed at the
     tip: run bisect the same way, substituting a verifier-invocation command
     for `--gate-command`. Because `--gate-command` is one fixed shell string
     reused unchanged for every reassembled subset, `--head-sha` cannot be
     supplied as a plain flag value (there is no per-attempt templating
     point) — embed a command substitution inside the string instead, so the
     shell re-resolves it fresh for each subset's own tip at the moment that
     subset's gate command actually runs:
     ```bash
     --gate-command "land-work/scripts/land-work-run-verifier.py --repo-root <repo-root> --candidate <integration-worktree> --base-sha <leased-sha> --head-sha \$(git -C <integration-worktree> rev-parse HEAD) --runtime <runtime>"
     ```
     (escape the `$(...)` so it survives whatever quoting wraps the whole
     `--gate-command` value, and only expands when the shell that
     `land-work-batch-bisect.py` invokes actually runs the command, inside
     that subset's freshly-reassembled worktree.)
   - A gate command that writes a non-gitignored artifact (a coverage report,
     a generated file) leaves it untracked in the shared worktree after that
     attempt. `land-work-batch-assemble.py`'s own foreign-untracked-files
     guard then refuses the *next* reassembly in the bisect loop, which
     aborts the whole bisect as an infra failure rather than a false
     "resolved" verdict — but it does mean `landing.full_gate` (or a
     verifier wrapper used as `--gate-command`) must not write anything
     outside `.gitignore` for a batch-mode repo, or bisect cannot run more
     than one attempt.
6. **Lease-checked advance.** On a green gate and verifier, re-verify the
   lease against the same SHA captured in step 2:

   ```bash
   land-work/scripts/land-work-verify-lease.py --expected-sha <leased-sha>
   ```

   Abort (do not push) if the lease no longer matches — the batch retries
   assembly on the new base rather than pushing over someone else's landing.
   On a matching lease, push the worktree's current tip directly onto the
   primary branch:

   ```bash
   git -C <integration-worktree> push origin HEAD:refs/heads/<primary-branch>
   ```

   This is a plain (non-force) push: the worktree's HEAD is a strict
   fast-forward descendant of the leased base by construction (step 3 always
   resets to that base first), so git's own fast-forward check is the second,
   independent guarantee behind the explicit lease re-check — a primary ref
   that moved between steps 2 and 6 makes this push fail even if the lease
   re-check were somehow skipped. The primary ref moves exactly once, to the
   gated tip; interior per-branch merge commits enter history but the ref
   never pointed at them individually.
7. **Post-land, per assembled branch.** For each entry in
   `land-work-batch-assemble.py`'s `assembled` list (not the evicted ones):
   close its tracker issue with gate evidence naming the batch tip SHA (not a
   per-branch SHA — the gate ran once, at the tip, covering the whole batch),
   then remove that branch's feature worktree and delete its branch, exactly
   as the serial teardown in step 10 does.
8. **Persistent worktree, not a preview.** Unlike the serial path's scratch
   `/tmp` preview, the integration worktree survives after landing — do not
   run `land-work-create-preview.py --cleanup` against it (that call is a
   documented no-op there anyway; see `references/integration-worktree.md`).

See `references/batch-landing.md` for the full mechanics, worked examples,
and the bisect protocol's `## Bisect` section. The queue/linger timing policy
itself remains out of scope here — it lives in the `swarm` skill.

## Non-Negotiable Rules

- Do not close the issue before the verified merge succeeds.
- Do not merge unless the discovered gate suite passes on the exact candidate
  (step 6a) or a waiver is recorded; never claim green when no suite was found.
- Do not merge unless `land-work-run-verifier.py` exits 0 on the exact merge
  preview. A verifier that returns zero selected checks against a real diff is a
  landing failure, not verified evidence. A generic `pre` hook's exit 0 never
  substitutes for it.
- Do not land onto a primary branch that is already red on a discovered gate.
- Do not close without gate evidence in the note — commands and exit statuses,
  not the bare claim that tests pass.
- Do not fast-forward feature branches into the primary branch unless the repo
  explicitly requires it.
- Always use regular merge commits (`--no-ff`). Never squash.
- Do not treat pre-rebase, pre-merge, or pre-conflict verification as valid
  for a changed landing candidate.
- Do not merge if the leased primary-branch ref moved after verification.
- Do not land from a dirty feature-branch checkout.
- Do not remove the feature worktree while untracked files created during the
  task remain unaccounted for. Each must be committed, gitignored, or deleted;
  plan/log/handoff files must not remain untracked.
- Do not delete a merged feature branch before removing its linked worktree.
- Do not leave a land-work preview/scratch worktree behind. Remove it on every
  exit path — verified landing, aborted lease, or error after creation — so no
  `/tmp/land-work-preview-*` worktree stays registered or on disk.
- Do not change the repository's configured Git transport just because auth
  fails.
- Do not bypass exact-candidate verification after manual conflict resolution.
- Do not use a repo-specific merge helper autonomously unless it can prove the
  landed candidate matches the verified preview.
- A missing verifier manifest triggers `wire-land-verifier` inline, not a bare
  halt — but `wire-land-verifier`'s own confirm-before-draft and
  explicit-go-ahead-before-apply gates still apply in full; auto-invoking it
  never substitutes for repo-owner confirmation of the real gate command.
- Do not skip discovered hook scripts or hook skills at the `pre` and `post`
  positions. At `pre`, a `75` exit (hook scripts) or matched stop condition
  (hook skills) halts before the merge starts and is a human handoff. At
  `post`, both are advisory: surface the message and continue.
- Do not land changes that include deploy-critical artifacts without verifying
  the committed blob content matches what was tested locally.

## Anti-Rationalization

| Excuse | Counter-argument |
|---|---|
| "Tests passed before the rebase, so the branch is verified." | Verification attaches to the exact candidate being landed. Rebase, merge, cherry-pick, conflict resolution, or artifact regeneration makes earlier results stale. |
| "The primary branch probably did not move; the lease check is ceremony." | Landing is compare-and-set. If the leased ref moved after verification, the verified candidate is no longer the candidate that would land. |
| "This repo usually accepts quick merges, so I can fast-forward or squash." | The default landing record is a regular merge commit unless the repo explicitly requires otherwise. Fast-forward and squash erase the branch boundary this workflow relies on. |
| "The issue is functionally done, so I can close it before merging." | Tracker closure advertises landed availability to dependent work. Closing before verified landing can make downstream agents claim work against code that is not on the integration branch. |
| "The diff is simple; I can skip the preview/exact-candidate checks." | Simplicity does not prove candidate identity. Preview, lease, and landing verification protect against stale bases, helper mismatch, generated artifacts, and accidental local-only state. |
| "Closure will clean up my just-landed branch." | The landing agent owns direct post-merge cleanup: leave the feature worktree, remove that worktree, then delete the merged branch. Closure is only a fallback for stale or ambiguous leftovers. |
| "The landing is done; the preview worktree under /tmp is harmless to leave." | Preview worktrees are registered git worktrees, not loose temp files. Left behind, they accumulate across landings and make every later `git worktree` probe slower or crash-prone. Remove the preview on every exit path; closure is not your janitor for worktrees you created this run. `land-work-create-preview.py` also refuses to start a new preview while a leftover one is still registered, and `land-work-verify-landing.py --preview-dir` fails the landing if cleanup was skipped — so this is enforced, not just prose. |
| "The change is small and I ran the tests locally earlier, so gates are fine." | Earlier or partial runs are not evidence for the exact candidate, and "small" does not exempt a change from the repo's gates. |
| "The primary branch was already red, but my branch didn't break it." | Landing on a red base hides which change is responsible and lets breakage linger. Halt on a pre-existing red base. |
| "The project verifier exited 0, so the candidate is verified." | Exit 0 alone is not evidence. A verifier can select zero checks for a real diff and still exit 0. `land-work-run-verifier.py` fails closed unless every landed path is covered by a passed selected check or an exact exemption. |
| "No manifest exists yet; I'll just tell the user to run `wire-land-verifier` later and stop here." | Verifier setup is per-project and gets forgotten until the next landing hits the same wall. Invoke `wire-land-verifier` now, in this session — its own confirmation and go-ahead gates still protect against a rubber-stamped verifier. |
| "I'll just type the compare-and-set commands by hand; it's the same steps `land.py` runs anyway." | `land.py` exists precisely because those nine hand-typed commands are where landings actually fail in practice — a skipped cleanup, a stale lease left unrechecked, a preview leaked on interrupt. Prefer it; fall back to the manual flow only when it is unavailable or you need to intervene mid-sequence. |

## Tracker Handoff

- If the project uses Beads, use the `beads-issue-flow` skill to close or update
  the issue after merge. Beads' `.beads/issues.jsonl` is a passive Dolt export
  and may be intentionally untracked (gitignored) to avoid concurrent-landing
  conflicts; do not re-add or commit it during landing.
- If the project uses GitHub Issues, use the `github-issue-flow` skill.

## Direct Integration Branch Overlay

If the repo intentionally merges directly into its real integration branch,
read `references/direct-primary-branch.md` before landing. That overlay only
clarifies how to identify and target the actual integration branch; it does not
replace the safety rules or merge flow above.
