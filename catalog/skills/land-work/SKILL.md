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
  once verification finishes). The preview helper refuses to proceed if the
  feature branch still tracks `.launch-work/log.md` or has any
  `chore(launch-work-log):` commit in the merge range; run
  `land-work-clean-log.py --apply` first.
- `land-work/scripts/land-work-verify-lease.py --expected-sha <sha>` to verify
  the landing lease still matches the intended primary-branch ref
- `land-work/scripts/land-work-verify-landing.py --expected-tree <tree>` to
  verify the landed primary-branch ref still matches the verified candidate
- `land-work/scripts/land-work-clean-log.py --base <ref> [--apply] [--keep-commits]`
  to identify log-only commits, drop them via non-interactive rebase, and
  remove `.launch-work/log.md` before the merge

Invoke these helpers by script path, not `python3 <script>`, so approvals stay
scoped to the script.

Run the prepare helper from the feature-branch worktree first. Use the preview
helper to create the exact candidate you will verify, the lease helper whenever
you capture or re-check the compare-and-set merge lease, and the landing
verifier after merge before closing tracker work.

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
land-work/scripts/land-work-prepare.py --require-up-to-date
```

2. Confirm the current branch is the intended landing branch and that the helper
   reports a clean feature-branch checkout.
2a. **Legacy migration only** — current launch-work stores the progress log
    under `$GIT_DIR/launch-work/log.md`, which never enters the working tree
    and never lands. If the working tree still carries a tracked
    `.launch-work/log.md` (a branch started before the move), run the
    log-cleanup pass before rebasing or verifying:

    - Verify the log's `checkpoint` is `ready-to-land`. If it is not, stop
      and ask the user — the work is not actually ready, or the agent forgot
      to update the log.
    - Preview the cleanup:

```bash
land-work/scripts/land-work-clean-log.py --base <primary>
```

    - Apply the cleanup:

```bash
land-work/scripts/land-work-clean-log.py --base <primary> --apply
```

    - On rebase conflict (a non-log commit also touched the log file), retry
      with `--apply --keep-commits` to accept the log-only commits as clutter
      and proceed; the deletion commit still runs.
    - The rebase rewrites local history. The next steps assume the rewritten
      branch.
3. Treat any verification that ran before a rebase, merge, cherry-pick, or
   manual conflict resolution as stale evidence only. It does not authorize a
   landing after the candidate changes.
4. Review the landing diff for design concerns mechanical checks miss:
   - Optional capabilities that crash instead of degrading on missing resources.
   - Committed artifacts diverging from workspace state (see
     `references/artifact-verification.md` when binary or LFS files are in
     the diff).
   - Container build inputs that differ between local and remote platforms.
   Use `requesting-code-review` for this step if available.
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

   - abort if the lease changed
   - commit and push only if the lease still matches
   - verify the landed primary-branch ref still matches the verified preview:

```bash
land-work/scripts/land-work-verify-landing.py --expected-tree <tree>
```

   - remove the preview worktree once verification has succeeded; the
     directory is a registered git worktree and accumulates under `/tmp`
     otherwise:

```bash
land-work/scripts/land-work-create-preview.py --cleanup --preview-dir <preview-dir>
```
9. After the landing succeeds, close or update the tracker item through the
   repo's tracker workflow. Follow `references/workflow-invariants.md`:
   mutate tracker state only after the work is verified as landed on the
   detected primary branch.
10. Clean up the merged feature branch and its linked worktree by handing off
    to `closure` in single-target mode. Return to the repo root on the primary
    branch first (you cannot remove the worktree you are standing in), then
    run:

    ```bash
    closure/scripts/closure-scan.py --target-branch <feature-branch> --apply delete-local-merged-branches
    ```

    The helper enforces the ordering rule from
    `references/workflow-invariants.md`: it removes the linked worktree before
    deleting the branch. Inspect `applied_actions` and `skipped_actions` in
    the output. If the helper skipped because of liveness, dirty state, or an
    in-flight `.launch-work/log.md`, resolve that condition and re-run rather
    than constructing manual `git branch -D` or `git worktree remove`
    commands.

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
- Do not change the repository's configured Git transport just because auth
  fails.
- Do not bypass exact-candidate verification after manual conflict resolution.
- Do not use a repo-specific merge helper autonomously unless it can prove the
  landed candidate matches the verified preview.
- Do not land changes that include deploy-critical artifacts without verifying
  the committed blob content matches what was tested locally.
- Do not merge a feature branch whose log (under `$GIT_DIR/launch-work/log.md`
  or, on legacy branches, `<worktree>/.launch-work/log.md`) reports a
  `checkpoint` other than `ready-to-land`.
- Do not skip the legacy log-cleanup pass when the working tree still tracks
  `.launch-work/log.md`. The preview helper enforces this and refuses any
  candidate that tracks `.launch-work/log.md` or contains a
  `chore(launch-work-log):` commit in the merge range.
- Use `--keep-commits` only when the rebase reports a conflict, or when the
  user explicitly accepts log-commit clutter in the primary branch.
- Launch-work scaffolding never lands on the integration branch. The current
  log location (`$GIT_DIR/launch-work/log.md`) makes this structural; the
  legacy cleanup pass exists only to migrate branches started before the
  move.

## Tracker Handoff

- If the project uses Beads, use the `beads-issue-flow` skill to close or update
  the issue after merge.
- If the project uses GitHub Issues, use the `github-issue-flow` skill.

## Direct Integration Branch Overlay

If the repo intentionally merges directly into its real integration branch,
read `references/direct-primary-branch.md` before landing. That overlay only
clarifies how to identify and target the actual integration branch; it does not
replace the safety rules or merge flow above.
