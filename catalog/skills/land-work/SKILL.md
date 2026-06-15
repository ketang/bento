---
name: land-work
description: Hard trigger — invoke after finishing your own approved feature-branch work to merge it, close tracker work, and tear down the feature branch and its linked worktree afterward. This is the routine post-merge cleanup path for the agent that did the work; do not use closure for that.
recommended_model: high
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

- `land-work/scripts/land-work-prepare.py` to verify the current checkout is a
  clean feature-branch worktree with something to land and, when requested,
  that it is not stale relative to the primary branch
- `land-work/scripts/land-work-create-preview.py` to materialize the exact
  merge candidate from the leased primary-branch base into a preview checkout
  (and `--cleanup --preview-dir <path>` to remove that registered worktree
  once verification finishes)
- `land-work/scripts/land-work-verify-lease.py --expected-sha <sha>` to verify
  the landing lease still matches the intended primary-branch ref
- `land-work/scripts/land-work-verify-landing.py --expected-tree <tree>` to
  verify the landed primary-branch ref still matches the verified candidate

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
   a fresh full-quality-gate run and an explicit review checkpoint on the
   resolved candidate before landing.
6. Push the feature branch with `--force-with-lease` if rebasing changed
   history.
7. Prefer the repo's documented merge helper if one exists only when it can
   prove or preserve the same exact candidate you verified. If the helper
   cannot expose equivalent candidate evidence, fall back to the explicit
   compare-and-set flow below.
8. Otherwise, perform a compare-and-set merge flow as separate commands, not
   one compound command string:
   - refresh the primary-branch ref you intend to lease
   - capture its SHA
   - create the merge preview the repo expects with:

```bash
land-work/scripts/land-work-create-preview.py --base-ref <sha>
```

   - run the full required verification gate against that exact preview only;
     do not reuse pre-rebase or pre-conflict results
   - re-check the lease with:

```bash
land-work/scripts/land-work-verify-lease.py --expected-sha <sha>
```

   - abort if the lease changed — and before stopping, remove the preview
     worktree (the cleanup command below); an aborted landing must not leave
     its scratch worktree registered
   - commit and push only if the lease still matches
   - verify the landed primary-branch ref still matches the verified preview:

```bash
land-work/scripts/land-work-verify-landing.py --expected-tree <tree>
```

   - **Always** remove the preview worktree once you are done with it, on every
     exit path — verified landing, aborted lease, or any error after the
     preview was created. It is a registered git worktree and otherwise
     accumulates under `/tmp` until a manual closure sweep removes it:

```bash
land-work/scripts/land-work-create-preview.py --cleanup --preview-dir <preview-dir>
```

     `land-work-create-preview.py` already removes its own worktree when the
     preview itself fails (merge conflict or error), reporting
     `"preview_cleaned_up": true`. The explicit cleanup above covers the
     success and abort paths, which the helper cannot clean for you because
     you still need the preview to verify the landing.
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
   detected primary branch.
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
    closure's liveness gate is built around recently-active worktrees and
    will skip your own.

## Non-Negotiable Rules

- Do not close the issue before the verified merge succeeds.
- Do not fast-forward feature branches into the primary branch unless the repo
  explicitly requires it.
- Always use regular merge commits (`--no-ff`). Never squash.
- Do not treat pre-rebase, pre-merge, or pre-conflict verification as valid
  for a changed landing candidate.
- Do not merge if the leased primary-branch ref moved after verification.
- Do not land from a dirty feature-branch checkout.
- Do not delete a merged feature branch before removing its linked worktree.
- Do not leave a land-work preview/scratch worktree behind. Remove it on every
  exit path — verified landing, aborted lease, or error after creation — so no
  `/tmp/land-work-preview-*` worktree stays registered or on disk.
- Do not change the repository's configured Git transport just because auth
  fails.
- Do not bypass exact-candidate verification after manual conflict resolution.
- Do not use a repo-specific merge helper autonomously unless it can prove the
  landed candidate matches the verified preview.
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
| "The landing is done; the preview worktree under /tmp is harmless to leave." | Preview worktrees are registered git worktrees, not loose temp files. Left behind, they accumulate across landings and make every later `git worktree` probe slower or crash-prone. Remove the preview on every exit path; closure is not your janitor for worktrees you created this run. |

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
