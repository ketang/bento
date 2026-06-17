---
name: launch-work
description: Hard trigger — always invoke before any edit to files inside a repository working tree; non-repo outputs (/tmp, scratch, memory dirs) and tracker-only mutations are exempt. Creates branch+worktree. Never skip for small changes.
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

## Trigger Scope

The trigger fires before any edit to files inside a repository working tree.
These are exempt and do not require a branch or linked worktree:

- writes under `/tmp` or other scratch paths outside the repo
- agent memory directories
- review reports and handoff files written outside the working tree
- tracker-only mutations (create, claim, update, close issues)

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

   When the repo uses a tracker but no specific issue has been identified for
   this work, scan open issues before creating anything:
   - Run the tracker's list command and read titles and descriptions of open
     issues for one that covers the current task.
   - If a match is found, use it — claim it per the repo's active-work policy
     and proceed.
   - If no issue matches well, file a new one via the tracker skill's filing
     flow (including its pre-filing review step), claim it, then proceed.
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
   primary checkout. Then read `launch-work/references/project-hook-scripts.md` and
    `launch-work/references/project-hook-skills.md`. Run the **`pre`** hook
    scripts after worktree verification and before dependency installation:

    ```bash
    launch-work/scripts/run-lifecycle-extensions.py run-hooks \
      --repo-root <repo-root> \
      --skill launch-work \
      --position pre \
      --branch <branch> \
      --worktree <worktree> \
      --base-ref <primary-branch> \
      --runtime <runtime>
    ```

    Then discover and apply hook skills for the `pre` position:

    ```bash
    launch-work/scripts/run-lifecycle-extensions.py discover \
      --repo-root <repo-root> \
      --skill launch-work \
      --kind hook-skills \
      --position pre
    ```

    Use `claude`, `codex`, or `unknown` for `<runtime>` to match the current
    agent runtime. Read each listed file in order. Treat any `## Stop
    conditions` predicate as a halt signal. If a hook script exited non-zero,
    follow the contract's abort or human-handoff semantics; hook skills do not
    load in that case.
10. Install build/runtime dependencies in the new worktree before the first
    build, test, or typecheck. Prefer the repo's documented bootstrap command;
    otherwise detect by lockfile per
    `launch-work/references/dependency-bootstrap.md`, which also covers
    disk-efficient choices on ext4 (pnpm store, shared module caches). Avoid
    overriding global cache directories per worktree unless the repo documents
    a reason to do so.

11. Before editing implementation code for new work or a behavioral change
    with feasible automated coverage, identify the relevant verification
    target and write or update the smallest relevant test so it fails against
    the current or missing behavior. Commit the failing test, then implement
    the change, make the test pass, and run the relevant verification gates.

12. Run the **`post`** hook scripts before declaring the work ready to land:

    ```bash
    launch-work/scripts/run-lifecycle-extensions.py run-hooks \
      --repo-root <repo-root> \
      --skill launch-work \
      --position post \
      --branch <branch> \
      --worktree <worktree> \
      --base-ref <primary-branch> \
      --head-sha $(git rev-parse HEAD) \
      --runtime <runtime>
    ```

    Then discover and apply `post` hook skills:

    ```bash
    launch-work/scripts/run-lifecycle-extensions.py discover \
      --repo-root <repo-root> \
      --skill launch-work \
      --kind hook-skills \
      --position post
    ```

    Use `claude`, `codex`, or `unknown` for `<runtime>` to match the current
    agent runtime. Read each listed file in order. Apply additive guidance and
    evaluate `## Stop conditions` predicates. If a hook script or hook skill
    halts,
    preserve branch and linked worktree and surface the message.

13. In the final task summary, include a brief note describing any additions
    or expansions made to the automated test suite. If test coverage did not
    change, say so explicitly.

## Concurrent-Safe Solo Work

Even outside an explicit swarm, other agents may be active in the same repos.
The `swarm` skill covers the coordinated case; these hazards also hit a single
agent working a focused task while others happen to share the tree. Apply this
hygiene whenever concurrent activity is possible:

- Pin your own linked worktree **and** your own build/target dir. Never reason
  about a binary or artifact you did not just build in your own tree.
- Verify git and process state before attributing observed behavior to code:
  whose worktree is this, whose uncommitted changes are present, is another
  build running? Confirm the source-to-binary chain before drawing conclusions.
- Expect shared-machine load. Cap parallelism and do not interpret slow or
  flaky builds as logic failures — re-run before debugging.
- Treat the tracker as contended. Commits to `.beads` can race; re-check issue
  state before concluding it is stale or wrong.

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
- Do not skip discovered hook scripts or hook skills at the `pre` and `post`
  positions. A `75` exit code (hook scripts) or matched `## Stop conditions`
  predicate (hook skills) is a human handoff, not a destructive failure;
  preserve the branch and linked worktree and surface the message.

## Anti-Rationalization

| Excuse | Counter-argument |
|---|---|
| "This is a tiny docs/config edit; a worktree would be overhead." | Content type and size are not exceptions. Any repo-artifact edit needs the dedicated branch and linked worktree so the primary checkout stays untouched and the task remains landable. |
| "Main is already dirty, so I might as well edit there." | Existing primary-checkout dirt is not permission to add more. Treat those changes as someone else's state and isolate this task in its own worktree. |
| "An old branch/worktree is close enough to reuse." | A branch/worktree pair records ownership and scope. Reusing it mixes histories, claims, hooks, and cleanup decisions across tasks. Create a fresh pair for this approved scope. |
| "I'll claim or file the issue after I make progress." | Tracker claims prevent duplicate work and encode ownership before implementation. If the repo uses active-work claims, inspect and claim before editing. |
| "The hook/action probably does not matter for this change." | Project extensions are part of the repo's local contract. Skipping them bypasses stop conditions and project-specific checks that the base skill cannot know. |
| "I'll add tests after the implementation works." | For new work or behavioral changes with feasible coverage, the failing test is the specification checkpoint. Deferring it invites unverifiable changes and stale final summaries. |

## Stop Conditions

Stop and ask or re-plan if:

- The approved scope is ambiguous or contradictory.
- The repo requires a claim model you cannot identify.
- The repo requires branch or worktree conventions that you cannot verify.
- The helper preview says the target branch or worktree is unsafe to create.
