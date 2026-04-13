---
name: launch-work
description: Hard trigger — invoke BEFORE any Edit, Write, or file-modifying Bash command; if the tree is already dirty, halt and apply this first. Claims work, creates branch+worktree, bootstraps env.
recommended_model: mid
---

# Launch Work

## Model Guidance

Recommended model: mid.

Use a higher-capability model when the repo's claim, branch, or worktree policy
is only partially documented or spans multiple tools.

Use this skill when a task has been approved for implementation and the repo's
branch, worktree, and claim rules are documented clearly enough to start work
safely.

## Inputs

- The active issue or approved change scope
- The repo's documented claim model, if any
- The repo's documented branch and worktree conventions, if any
  - When the repo does not override the worktree root, use the shared default
    `~/.local/share/worktrees/<repo>/<branch>`

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
3. If the repo requires claiming active work, inspect and claim it before
   implementation begins.
4. Determine the target branch name and linked-worktree path from repo docs.
   - If the repo does not define a different root, use
     `~/.local/share/worktrees/<repo>/<branch>`.
5. Preview the setup with:

```bash
launch-work/scripts/launch-work-bootstrap.py --branch <name> --worktree <path>
```

6. If the preview is correct, create the linked worktree with:

```bash
launch-work/scripts/launch-work-bootstrap.py --branch <name> --worktree <path> --apply
```

7. Enter the linked worktree and verify both location and branch:

```bash
launch-work/scripts/launch-work-verify.py --expected-branch <name> --expected-worktree <path> --require-linked-worktree
```

8. Confirm implementation will happen in that linked worktree, not in the
   primary checkout.
9. Before editing implementation code for a behavioral change with feasible
   automated coverage, identify the relevant verification target and write or
   update a test so it fails against the current behavior. Then implement the
   change, make the test pass, and run the relevant verification gates.
10. If the fresh worktree cannot resolve dependencies, run the repo's documented
   install/bootstrap step before debugging build failures.

## Non-Negotiable Rules

- One approved task gets one branch and one linked worktree.
- Do not repurpose an old branch or worktree for a different task.
- Do not implement directly on the detected primary branch.
- Do not implement from the primary checkout when the repo expects worktree
  isolation.
- For behavioral changes with feasible automated coverage, use a red/green
  workflow: write or update a test that fails before implementing the change,
  then make it pass.
- Do not place linked worktrees under `/tmp` unless the repo explicitly
  documents that as safe and durable enough for the task.
- Do not skip claim steps when the repo uses a tracker-backed active-work model.
- If automated coverage is not feasible, state that explicitly and use the
  closest available verification path.

## Stop Conditions

Stop and ask or re-plan if:

- The approved scope is ambiguous or contradictory.
- The repo requires a claim model you cannot identify.
- The repo requires branch or worktree conventions that you cannot verify.
- The helper preview says the target branch or worktree is unsafe to create.
