---
name: launch-work
description: Hard trigger — invoke before implementation edits or file-modifying Bash commands that change code or repo-managed artifacts. Do not use this skill for tracker-only mutations such as creating, claiming, updating, or closing issues. If the tree is already dirty from implementation work in the current session, halt and apply this first. Claims work, creates branch+worktree, bootstraps env.
recommended_model: mid
---

# Launch Work

## Model Guidance

Recommended model: mid.

Use a higher-capability model when the repo's claim, branch, or worktree policy
is only partially documented or spans multiple tools.

Use this skill when a task has been approved for implementation and the repo's
branch, worktree, and claim rules are documented clearly enough to start work
safely. Do not invoke it for tracker-only administration with no planned code
or repo-artifact edits.

## Inputs

- The active issue or approved change scope
- The repo's documented claim model, if any
- The repo's documented branch and worktree conventions, if any. For
  linked-worktree placement, follow
  `launch-work/references/worktree-location.md`.

## Deterministic Helpers

This skill includes helper scripts under `launch-work/scripts/` for the parts
of launching work that benefit from repeatable checks:

- `launch-work/scripts/launch-work-bootstrap.py --branch <name> --worktree <path>`
  to preview or apply branch and linked-worktree creation
- `launch-work/scripts/launch-work-verify.py --expected-branch <name> --expected-worktree <path> --require-linked-worktree`
  to verify the current checkout is the intended linked worktree on the intended
  branch

Invoke these helpers by script path, not `python3 <script>`, so approvals stay
scoped to the script.

Use the bootstrap helper in dry-run mode first. Add `--apply` only after the
target branch and worktree path are confirmed correct.

## Workflow

1. Read the repo's local instructions and confirm the approved task scope.
2. Determine whether the work is tracker-backed or just an approved change.
   - If the repo uses Beads, use the `beads-issue-flow` skill.
   - If the repo uses GitHub Issues, use the `github-issue-flow` skill.
   - If the work is not tracker-backed, record that explicitly and continue.
3. If the current task is only to create, inspect, claim, update, or close a
   tracker item, follow the tracker skill directly and do not create a branch
   or linked worktree unless the repo explicitly requires that workflow.
4. If the repo requires claiming active work, inspect and claim it before
   implementation begins.
5. Determine the target branch name and linked-worktree path from repo docs.
   Follow `launch-work/references/worktree-location.md` for the default root,
   prohibited locations, and override guidance.
6. Preview the setup with:

```bash
launch-work/scripts/launch-work-bootstrap.py --branch <name> --worktree <path>
```

7. If the preview is correct, create the linked worktree with:

```bash
launch-work/scripts/launch-work-bootstrap.py --branch <name> --worktree <path> --apply
```

8. Enter the linked worktree and verify both location and branch:

```bash
launch-work/scripts/launch-work-verify.py --expected-branch <name> --expected-worktree <path> --require-linked-worktree
```

9. Confirm implementation will happen in that linked worktree, not in the
   primary checkout.
10. Before editing implementation code for new work or a behavioral change with
    feasible automated coverage, identify the relevant verification target and
    write or update the smallest relevant test so it fails against the current
    or missing behavior. Then implement the change, make the test pass, and run
    the relevant verification gates.
11. Install build/runtime dependencies in the new worktree before the first
    build, test, or typecheck. Prefer the repo's documented bootstrap command;
    otherwise detect by lockfile per
    `launch-work/references/dependency-bootstrap.md`, which also covers
    disk-efficient choices on ext4 (pnpm store, shared module caches). Avoid
    overriding global cache directories per worktree unless the repo documents
    a reason to do so.
12. In the final task summary, include a brief note describing any additions or
    expansions made to the automated test suite. If test coverage did not
    change, say so explicitly.

## Non-Negotiable Rules

- One approved task gets one branch and one linked worktree.
- Do not repurpose an old branch or worktree for a different task.
- Do not implement directly on the detected primary branch.
- Do not implement from the primary checkout when the repo expects worktree
  isolation.
- Tracker-only mutations are not implementation and do not require
  branch/worktree setup unless the repo explicitly requires it.
- For new work and behavioral changes with feasible automated coverage, use a
  red/green workflow: write or update the smallest relevant test so it fails
  before implementing the change, then make it pass.
- Final task summaries should call out any automated test-suite additions or
  expansions, or explicitly state that test coverage was unchanged.
- Follow the placement prohibitions in
  `launch-work/references/worktree-location.md`.
- Do not skip claim steps when the repo uses a tracker-backed active-work model.
- If automated coverage is not feasible, state that explicitly and use the
  closest available verification path.

## Stop Conditions

Stop and ask or re-plan if:

- The approved scope is ambiguous or contradictory.
- The repo requires a claim model you cannot identify.
- The repo requires branch or worktree conventions that you cannot verify.
- The helper preview says the target branch or worktree is unsafe to create.
