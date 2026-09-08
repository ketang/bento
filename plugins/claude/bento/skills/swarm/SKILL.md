---
name: swarm
description: Use when multiple ready tasks can be worked in parallel — triage, batch non-overlapping work, launch isolated worktrees, review plans, land safely.
---

# Swarm

## Model Guidance

Recommended model: high — triage, overlap prediction, and multi-teammate
coordination degrade sharply on smaller models.

Use this skill when a project has multiple ready tasks that can be worked in
parallel with good isolation.

## Inputs

- The candidate task list, or a documented tracker query that can produce it
- The project's documented tracker workflow
- The project's documented branch, worktree, and landing conventions
- The project's required quality gates and any pre-completion checks
- Optional landing target branch (defaults to the detected primary branch).

## Deterministic Helpers

This skill includes local helper scripts under `swarm/scripts/`:

- `swarm/scripts/swarm-discover.py` — git-derived defaults plus any structured
  swarm config the repo exposes, including a validated, defaulted `landing`
  block (see `swarm/references/landing-config.md` for the schema and its
  fail-safe validation rules)
- `swarm/scripts/swarm-triage.py --input <json>` — batch normalized task data
  into unblocked frontier, wait queues, and skips. Run `--help` for the input
  schema and output category enum.
- `swarm/scripts/swarm-worktree-verify.py` — verify the current checkout is
  the expected linked worktree on the expected branch
- `swarm/scripts/swarm-post-land.py --hook <name> --landing-target <branch> --primary <branch>` — run a named post-land hook after a successful land. Use by script path, not `python3 <script>`.

Invoke these helpers by script path, not `python3 <script>`, so approvals stay
scoped to the script. They require `python3` on `PATH`. If `python3` is
unavailable, fall back to the prose workflow and perform checks manually.

Keep tracker fetching outside these helpers. Use the project's tracker workflow
to gather tasks, then normalize them into the triage input format.

## Continuation State

If a batch overflows the current run, persist remaining task IDs in
runtime-local state so a later invocation can resume without re-querying the
tracker. See `swarm/references/continuation-state.md` for runtime state roots,
`continue.txt`/`handoff.md` formats, and any runtime-specific pre-flight.

## Companion Skills

- If the project uses Beads, use `beads-issue-flow` for claiming and closing.
- If the project uses GitHub Issues, use `github-issue-flow`.
- Use `launch-work` for the exact branch and worktree bootstrapping rules.
- Use `land-work` for the final landing procedure when project docs do not
  define a stricter swarm-specific landing flow.

## Phase 0: Discover Project Rules

Before triage, read the project's local instructions and determine:

- how to list, inspect, and claim ready tasks
- which agent runtime is orchestrating the swarm and its teammate launch model
- how branches and worktrees are named
- where linked worktrees should live; default to
  `~/.local/share/worktrees/<repo>/<branch>` when the repo does not document a
  different durable root
- which quality gates apply per task and after all merges
- whether a pre-completion checklist or skill is required
- whether the tracker exposes explicit task dependencies
- how completed branches land on the integration branch
- whether post-land hooks are required

When the project exposes a structured swarm config, run the discovery helper
for the current runtime:

```bash
swarm/scripts/swarm-discover.py --runtime claude   # or --runtime codex
```

This loads the matching runtime-specific config if present and otherwise falls
back to the shared `swarm-config.json` at the repo root. Use the output as the
deterministic base layer, then fill remaining gaps from repo docs.

**Batch vs. serial mode.** Later phases refer to a "batch-mode repo" or
"serial-mode repo" — this always means `swarm-discover.py`'s reported
`landing.mode` output, the already fail-safe-validated value (see
`references/landing-config.md`), never the raw `swarm-config.json` file's
literal `mode` field read directly. A `mode: batch` config with a missing or
non-executable `gate_scope`/`full_gate` degrades to `serial` in that output,
specifically so a broken batch config can't silently run as an under-gated
batch; treat the degraded value as authoritative. **Batch-mode** means
`swarm-discover.py` reports `landing.mode: "batch"` — the queue/linger model
in `## Batch Landing` and the teammate scoped-gate contract (Phase 2-4 below)
apply. **Serial-mode** means everything else (no `swarm-config.json`,
`landing` absent, or `landing.mode` resolving to `"serial"`, including a
degraded batch config) — today's one-branch-at-a-time flow, entirely
unaffected by the batch-mode text throughout this skill.

If the project does not document these items clearly enough to swarm safely,
stop and ask the user to narrow the scope or clarify the workflow.

## Phase 1: Triage

1. Resolve the candidate task set from explicit task IDs or the documented
   tracker's ready-work query.
2. Inspect each task closely enough to understand scope, likely files, and
   whether it is small enough for one teammate.
3. For every task that remains eligible, capture a concise human-readable
   summary. Do not present only the tracker key or task ID when a short
   description can be derived from the issue title or body.
4. Present the proposed work items in a numbered table so each row can be
   referenced unambiguously during launch and follow-up. Include at minimum:
   row number, task ID, title, concise summary, predicted scope or paths, and
   any risk notes that affect batching.
5. Separate clearly launchable work from tasks that need extra handling.
6. Skip tasks already in progress, too large, ambiguous, or coupled for
   parallel execution.
7. Predict file overlap across candidates and with any active work. Batch only
   tasks that appear meaningfully isolated. Sequence tasks that touch shared
   hotspots (central schemas, shared config/types, generated outputs,
   high-churn framework entrypoints).
8. If the tracker exposes explicit dependencies, spawn only the currently
   unblocked frontier, then recompute readiness after each landed batch — not
   a flat queue.
9. When a teammate finishes and a slot opens, re-triage the remaining
   candidates against current active paths, hotspots, landed IDs, and newly
   unblocked dependencies before backfilling. Do not refill if every remaining
   task is still blocked or conflicting.
10. Seek user approval before spawning teammates only when the proposed batch
   has material complications, for example:
   - one or more tasks are too large for one teammate
   - issue scope or expected behavior is ambiguous
   - overlap, dependencies, or active-work conflicts make the launch order
     non-obvious
   - the tracker data is too thin to produce reliable summaries or scope
     estimates
   - the overall batch looks risky enough that autonomous launch would be hard
     to defend
11. If the selected batch is routine and the risks are well bounded, do not
   stop for approval. Summarize the numbered work-item table, note any skipped
   or deferred tasks, and proceed directly to teammate launch.

When the project can supply normalized task data, prefer:

```bash
swarm/scripts/swarm-triage.py --input triage.json
```

Run `swarm-triage.py --help` for the input schema and the output categories
(`parallel_batch`, `wait_queue`, `overflow`, `skipped`,
`deferred_due_to_dependencies`, `deferred_due_to_active_overlap`). The script
is tracker-agnostic; tracker-specific skills convert tasks into this format.

## Phase 2: Teammate Launch

Use the runtime's managed multi-agent flow, not ad hoc background workers.
Follow the runtime-specific launch and lifecycle requirements supplied with the
generated skill payload.

For each launched task: exactly one branch, exactly one worktree, and the
prompt must include task details, expected scope, overlap risks, required
quality gates, the row number from the triage table, and the working-hygiene
clause below. Include the landing
target branch in the teammate prompt so the teammate knows which branch their
work merges into. Require the teammate to stop and report back if the task is
broader or more coupled than expected.

For a batch-mode repo (Phase 0), the teammate scoped-gate contract applies:
include the `landing.gate_scope` command in the teammate prompt in place of
the repo's full fixed gate list, and instruct the teammate to run it against
their own final diff and execute every gate command it emits, reporting each
in the same ready-to-land Gate summary format below (which gates ran and
passed) — only the *set* of gates to run is scoped to the diff instead of
fixed; the reporting format itself does not change. Serial-mode repos (Phase
0) keep listing the repo's full fixed gate commands in the prompt, unchanged.

Teammate instructions must treat worktree placement as part of setup, not an
implementation detail. Require a durable dedicated root and reject placements
under `/tmp`, the top level of the user's home directory, the project parent,
or inside the checked-out repository unless the project explicitly documents
one of those locations.

Worktree setup MUST propagate the project's permission allowlist into the new
worktree. Claude Code reads project permissions from the `.claude/` directory
of the checkout it is operating in; a linked worktree only contains git-tracked
files, so an untracked `.claude/settings.json` or `.claude/settings.local.json`
in the primary checkout is absent in the worktree. Without it, workers stall
silently on Bash permission prompts even when spawned with
`mode: "bypassPermissions"`. At worktree setup time, before the worker starts
editing, symlink the primary checkout's settings into the worktree:

```bash
# Run from the worker worktree root, with PRIMARY set to the primary checkout.
mkdir -p .claude
for f in settings.json settings.local.json; do
  if [ -e "$PRIMARY/.claude/$f" ] && [ ! -e ".claude/$f" ]; then
    ln -s "$PRIMARY/.claude/$f" ".claude/$f"
  fi
done
```

Only create the symlink when the worktree does not already have that file (a
project that commits `.claude/settings.json` already ships it to every
worktree). The teammate prompt MUST require this step as part of worktree
bootstrap so the worker inherits the project's allowlisted command classes and
does not block on permission prompts.

The teammate must verify working directory and branch before any edits. Always
pass `--expected-branch` with the exact branch assigned to this task —
`--require-linked-worktree` alone only proves the teammate is in *some* linked
worktree, not the one assigned to this task, and will pass even from a
different task's worktree:

```bash
swarm/scripts/swarm-worktree-verify.py --require-linked-worktree --expected-branch <assigned-branch>
```

Reject any teammate setup that cannot show they are inside the intended
worktree on the intended branch.

Every teammate prompt MUST include a hard-gate clause to this effect, verbatim
or close to it, with `<assigned-branch>` filled in with this task's actual
branch name:

> **Do not edit any file, run any write command, or make any commit until
> `swarm-worktree-verify.py --require-linked-worktree --expected-branch
> <assigned-branch>` exits 0. If it exits non-zero, create or fix the
> worktree first, then re-run the script. Any edit before a passing verify is
> a protocol violation — `--require-linked-worktree` alone is not sufficient
> because it does not check that this is the worktree assigned to YOU.**

Every teammate prompt MUST also carry these working-hygiene rules, verbatim or
close to it:

> - Search and read with the `Grep`, `Glob`, and `Read` tools, not shell
>   `grep`/`cat`/`sed`/`find` pipelines.
> - Before any rebase or merge, run `git status --short` and commit or stash
>   deliberately; never retry `git stash pop` into a dirty tree.
> - If a long gate or background job is in flight, message the team lead before
>   going idle.

Teammates must use `../launch-work/scripts/run-heavy` when invoking build
commands in their worktrees (see the Heavy Job Protocol in `launch-work`
SKILL.md). Include this in every teammate prompt:

> **For heavy build commands (`cargo build/test`, `scripts/build-plugins`,
> bundlers, etc.) use the `launch-work` skill's `scripts/run-heavy <cmd>` so
> concurrent workers don't pile CPU and memory pressure on the shared
> machine.**

Teammates do not land their own work. The lead runs `bento:land-work` for
every completed branch. The teammate prompt must instruct the teammate to stop
after gates pass and signal the lead:

> **Do not invoke `land-work` or run any `git merge` or `git push` to the
> primary branch. When all quality gates pass and the branch is committed and
> pushed to the remote, SendMessage the lead with:**
> - **Branch name** (exact ref)
> - **Worktree path** (absolute)
> - **Tracker ID**
> - **Gate summary** — which gates ran and passed
> - **Any warnings or reviewer follow-up items**
>
> **Then exit. Do not close the tracker issue or delete the worktree — the
> lead handles both as part of landing. Do not wait for a reply.**

## Phase 3: Plan Review

Review each teammate plan for correct scope (no opportunistic extras), explicit
worktree+branch verification, correct quality gates, test coverage appropriate
to the task, no unresolved overlap with active teammates, and any required
pre-completion step. Reject plans that reference the primary checkout or do
not explain how the task will be verified.

For a batch-mode repo (Phase 0), a scoped-gate plan — one that runs
`landing.gate_scope`'s emitted commands against the teammate's own diff
instead of the repo's full fixed gate list — is acceptable under the teammate
scoped-gate contract; judge it on the same terms as a full-list plan (explicit
worktree+branch verification, correct gate execution, appropriate test
coverage, no unresolved overlap). Serial-mode repos (Phase 0) are unaffected:
a serial-mode plan must still run the repo's full fixed gate list.

Reject any teammate plan that does not include an explicit
`swarm-worktree-verify.py --require-linked-worktree --expected-branch
<assigned-branch>` step (or the equivalent worktree-verify gate with the
assigned branch passed) before any file edit. A plan that jumps straight to
edits without a passing verify is not acceptable, even if the teammate
claims to already be in the right worktree. A plan that verifies with
`--require-linked-worktree` alone, without `--expected-branch`, only proves
"some linked worktree" and does not satisfy this gate.

Reject any teammate plan that includes `land-work`, `git merge` to the primary
branch, or any other landing step. Landing is the lead's responsibility; a
teammate plan that attempts to land is a protocol violation.

## Anti-Rationalization

| Excuse | Counter-argument |
|---|---|
| "The tasks look independent from their titles; I can launch them together." | Titles are not enough to predict overlap. Inspect scope, likely paths, dependencies, and active work before batching, then re-triage after each landed branch. |
| "A teammate can fix worktree setup after starting edits." | Worktree verification is a hard gate before any file edit or write command. If verification fails, the teammate must stop and create or enter the correct worktree first. |
| "The teammate promised to be careful, so a weak plan is acceptable." | Plan review is the lead's safety checkpoint. Reject plans that omit branch/worktree proof, quality gates, test strategy, or overlap handling. |
| "Several teammates are done, so I can land them as a batch." | Landing changes the base for every remaining branch. Land one branch at a time, run required post-land hooks, then re-triage conflicts and readiness before continuing — unless the repo is batch-mode (Phase 0's "Batch vs. serial mode"), then follow the batch queue protocol in Phase 4's Batch-Mode Landing instead. |
| "The user is silent, so the human-gated step is approved." | Silence is not approval. Teammates park and idle, the lead serializes user attention, and work resumes only after the lead routes an explicit decision back. |
| "A stalled teammate is probably done enough to clean up." | Runtime resources close only after the work is safely landed or explicitly deferred. Never discard a teammate's branch or worktree while its status is unresolved. |
| "The teammate's gates all passed, so it can just run land-work itself." | Landing is the lead's job regardless of how clean the branch is. The auto mode classifier can block landing operations in teammate agents. The lead owns the single serialized landing path. |

## Phase 4: Monitor and Land

Teammates do not invoke `land-work`; the lead does, after receiving each
teammate's ready-to-land signal. What the lead does with that signal
diverges by landing mode (Phase 0's "Batch vs. serial mode" — never
re-derive the condition here): serial-mode repos land each signal alone,
immediately; batch-mode repos enqueue it and land it as part of a
lead-assembled batch. Steps 1-2 below are identical in both modes.

For each ready-to-land signal received:

1. Navigate to the teammate's worktree path. The teammate has already
   exited, so the worktree is unoccupied.
2. From within that worktree, confirm the gate summary in the teammate's
   signal covers all required gates for that task. For a batch-mode repo
   (Phase 0), do this under the teammate scoped-gate contract: re-run
   `landing.gate_scope` yourself, from within this same worktree (so it
   scopes the same diff the teammate's own final run scoped — the teammate's
   branch checked out against the landing target) — do not trust the
   teammate's self-report of which gates were "required" — and confirm the
   teammate's reported gate summary covers exactly that emitted set. For a
   serial-mode repo (Phase 0), this step is unchanged: confirm the gate
   summary covers the repo's full fixed gate list. If any gate is missing or
   failed, SendMessage the teammate to fix and re-signal; do not proceed.

### Serial-Mode Landing

Continue directly from step 2 above:

3. Invoke `bento:land-work` from within the teammate's worktree — land-work's
   cleanup step can remove it safely once landing succeeds.
4. If a post-land hook is configured for this swarm, run it after `land-work`
   completes:
   `swarm/scripts/swarm-post-land.py --hook <name> --landing-target <branch> --primary <branch> --apply`
   If the hook fails, stop and report — do not continue landing more branches
   until the hook succeeds.
5. Re-triage remaining branches against the new primary-branch base before
   landing the next one.

Never land more than one branch at a time, unless the repo is batch-mode
(Phase 0's "Batch vs. serial mode") — then follow Batch-Mode Landing below
instead. Each landing changes the base for all remaining branches.

When teammates are safely landed or explicitly deferred, close the runtime
resources that were created for them.

### Batch-Mode Landing

For a batch-mode repo (Phase 0), the lead runs a landing queue instead of
landing each confirmed signal alone. A branch confirmed in step 2 above does
not land immediately — it enters the queue, and the lead assembles, gates,
and lands a batch of queued branches together through `bento:land-work`'s
`## Batch Landing` sequence (resolve the integration worktree, capture the
lease, assemble, gate once at the tip, verify once at the tip,
lease-checked push, per-branch post-land teardown). This section covers only
*when* a batch starts, *what* joins it, and how its outcome routes back to
teammates — the assemble/gate/push mechanics themselves are `land-work`'s,
not restated here.

1. **Queue admission.** A branch confirmed in step 2 joins the queue. It
   does not land yet.
2. **Starting a batch.** The lead — acting as the batch runner through the
   integration worktree — is idle whenever no batch is currently assembling
   or gating. When the runner is idle and the queue is non-empty:
   - If no other teammates are currently active in the team, start
     assembling the queued branches into a batch immediately — the lead
     knows the team roster, so there is nothing left to wait for.
   - Otherwise, open a linger window of `linger_minutes` (landing config,
     default 5) measured from the first branch's arrival in the (until then
     empty) queue. This is a single window, not reset by later arrivals — a
     branch joining at minute 4 does not push the deadline to minute 9.
   - The window ends, and assembly starts on whatever is queued at that
     moment, at the earliest of: the window elapsing, the queue reaching
     `max_batch_size` (landing config, default 5), the last active teammate
     finishing (nothing left in flight that could still add to this batch),
     or a boundary branch arriving (step 4 below forces immediate closure
     regardless of the other three conditions).
3. **Assembly membership.** A branch confirmed while the linger window is
   still open (assembly has not started) joins the batch being formed. A
   branch confirmed while the runner is busy (a batch is currently
   assembling or gating) queues for the *next* batch instead.
4. **Boundary flush.** A branch touching any of the repo's
   `batch_boundary_paths` (landing config) does not queue with the rest.
   First close out the current batch: if one is queued or assembling, land
   it now (steps 5-8 below) before touching the boundary branch. Then land
   the boundary branch alone, under `landing.full_gate`, with no linger —
   the same immediate one-branch landing serial mode uses, just for this one
   branch. Once it lands, batching resumes for subsequently confirmed
   branches.
5. **Assemble, gate, land.** Hand the queued branch list to `bento:land-work`'s
   `## Batch Landing` sequence. Do not reimplement assembly, gating, or the
   lease-checked push here; this phase only decides when a batch starts and
   what belongs in it.
6. **Red batch → bisect.** If the tip gate or verifier comes back red,
   `land-work`'s `## Batch Landing` step 5 calls `land-work-batch-bisect.py`.
   Interpret its result with the corrected exit-code contract
   (`land-work/SKILL.md`'s `## Batch Landing` step 5 and
   `land-work/references/batch-landing.md`'s `## Bisect` section, "Reading
   the result"). The script's top-level `ok` already collapses to exactly
   two outcomes — do not invent a third by treating `final.ok: false` as
   distinct from `ok: false`; the script can never return `ok: true` with
   `final.ok: false`, since its own exit logic sets `overall_ok = final is
   None or bool(final["ok"])`:
   - `ok: true` — safe to proceed with `landable`. Two sub-cases: `final.ok:
     true` (`landable` is the subset to land, step 5 above; `culprits` go
     back to their teammates as rework) and `final: null` (every input
     branch turned out to be a culprit — a successful bisect outcome with
     nothing to land; return every originally assembled branch as rework,
     and reset the integration worktree before reusing it for the next
     batch, since bisection left it checked out at whatever the last attempt
     assembled, not at a clean base). Record the full `trail` in the
     tracker issue for the batch either way.
   - `ok: false` — land nothing; return every originally assembled branch
     as rework. Covers both `final.ok: false` (the confirmation gate on
     `landable` itself failed — a residual non-monotonic interaction
     pairwise halving didn't catch) and an infra failure (unregistered
     worktree, bad base-ref, a duplicate `--branch`, a branch evicted during
     a subset's reassembly, or the worktree becoming unusable mid-bisect).
     Record the trail and failure in the tracker issue for the batch.

   A branch returned as rework re-enters the normal Phase 1/3 lifecycle
   (teammate fixes, re-verifies, re-signals); it does not silently
   re-auto-queue.
7. **Re-triage, per batch.** After each batch lands (or a boundary branch
   lands alone), re-triage remaining in-flight branches against the new
   primary-branch base — the same rule the serial path applies after each
   landing (Serial-Mode Landing step 5 above), applied once per landed batch
   instead of once per landed branch.
8. **Teardown.** Per-branch tracker close and feature-worktree removal are
   `land-work`'s `## Batch Landing` step 7 (already covered by this
   section's intro, not restated here). What step 7 does not cover: if a
   post-land hook is configured for this swarm, run it once per landed
   batch (or once for a boundary branch landed alone) — the same hook
   invocation Serial-Mode Landing step 4 uses, just once per batch instead
   of once per branch.

Batch mode intentionally lands more than one branch per push — that is the
point of the feature. What does not change from serial mode: the lead is
still the only actor that ever touches the primary branch or the
integration worktree, and it still does so one action at a time — batching
changes when branches group together for landing, not who is allowed to
touch the shared worktree. No documented path in this skill drives two
concurrent land-work operations against the same integration worktree; see
`land-work/references/integration-worktree.md`'s "Known Limitation:
Single-Writer Assumption" and `bento-nmmk` for the (still deferred) locking
question this would raise if that ever changed.

## Phase 5: Final Validation

After all approved tasks are landed:

1. Run the project's full aggregate quality gate.
2. Confirm generated assets, schemas, or walkthrough artifacts are updated.
3. Summarize what landed, what was deferred, and any follow-up risks.

## Human-Gated Handoff

Backgrounded teammates cannot reach the user directly — the user typically
only watches the lead's window. Any teammate step that requires human
attention (visual review, manual test approval, destructive-op confirmation,
ambiguous-scope escalation, a project-supplied hook that exits with a
"requires human handoff" status — see `bento-2xe`) routes through the lead
using this protocol. Visual review is one example, not the only one.

1. **Teammate parks and idles.** When the teammate hits a human-gated step,
   it leaves the work in a safe state: branch unmerged, tracker issue still
   open and in-progress, linked worktree intact, no destructive cleanup, no
   `land-work` invocation. It SendMessages the lead with a structured
   handoff (see format below) and then idles. It does not poll, retry, or
   advance until the lead routes a decision back.

2. **Lead serializes user attention.** The lead is the single user-attention
   surface. When handoff messages arrive, the lead surfaces ONE review
   request at a time in its own window, or sends a single batched message
   with explicit ordering when several are pending. Multiple teammates must
   never ping the user in parallel through different channels.

3. **Lead routes the decision back.** The user replies to the lead. The
   lead SendMessages the originating teammate with the decision (approve /
   revise / reject, plus any specifics). The teammate never reads the user
   directly and never assumes silence means approval.

4. **Handoff message format.** Every handoff includes:
   - **Branch name** (exact ref).
   - **Tracker ID** (e.g., beads issue ID).
   - **Summary** — one line on what the teammate did.
   - **Command for the human** — exact command to run (e.g.,
     `pnpm test:manual auth-flow`, `git diff main..<branch> -- path/`, or a
     project-specific review command).
   - **What to look for** — the specific check the human is performing.
   - **How to reply** — what answer shape the teammate needs back
     (approve / revise with notes / reject).

## Claude Code Requirements

Launch teammates with Claude Code's managed team flow:

- Create a team with `TeamCreate`.
- Create one task per approved work item with `TaskCreate`.
- Start each teammate with `Agent`, setting `team_name`, a descriptive `name`,
  and `model: "sonnet"` by default. Override to a stronger model (e.g. `opus`)
  only when the task involves deep architectural judgment, ambiguous scope, or
  cross-cutting design decisions — note the override reason in the triage
  table's risk-notes column (Phase 1, step 4).

When the last Claude Code teammate in the batch is done, delete the team.
