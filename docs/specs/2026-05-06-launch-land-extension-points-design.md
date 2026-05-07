# Extension Points for launch-work and land-work

**Status:** design
**Tracker:** bento-5v2
**Date:** 2026-05-06

## Summary

Add structured extension points to the `launch-work` and `land-work` skills so
projects can run their own logic at the boundaries of those skills without
forking them. Two complementary mechanisms:

1. **Project hooks** — executable scripts (the existing mechanism, generalized
   to multiple position slots).
2. **Project actions** — markdown files containing plain-language instructions
   the agent reads and applies inline (new).

Both are optional. Repos with no hooks and no actions behave exactly as today.

## Motivation

The existing `project-hooks.md` contract supports a single injection point
per phase, located early in each skill ("after worktree verify" for
launch-work; "before merge preview" for land-work). That is enough for "run
a check before deps" or "run a check before the merge preview," but it does
not cover real needs that arise *at the skill boundaries*:

- **After launch-work completes** — e.g., post-setup verification, project
  scaffolding, or a per-task seed action that should run once the worktree and
  branch exist but before the user starts implementation.
- **Before land-work begins** — e.g., a project-specific preflight that must
  run as the very first action of the landing flow, before any preflight built
  into the skill itself.

Additionally, executable scripts cover the "deterministic gate" use case well
but are clumsy when the desired extension is *guidance for the agent* rather
than a binary check ("after launch-work, also do X"). Those reads more naturally
as a brief skill fragment than as a script.

## Goals

- Preserve the existing `project-hooks.md` contract verbatim for repos that
  already use it.
- Give projects a way to inject logic at two positions per skill — `pre` and
  `post` — for both hooks and actions.
- Support two extension flavors:
  - **Hooks**: opaque executables, exit-code semantics, env-var protocol.
  - **Actions**: markdown prose, additive and modifying, with an optional
    structured halt convention.
- Avoid built-in timeouts so interactive hooks (auth, prompts) work without
  ceremony; provide opt-in mechanisms for repos that want bounded runs.

## Non-goals

- Letting actions or hooks fully replace the skill's built-in workflow.
  Extensions are *additive* and may *modify*; full replacement is out of scope.
- Letting `post/` extensions reverse work the skill has already completed
  (e.g., a `land-work/post/` extension cannot "un-merge" a merge that already
  succeeded).
- Defining a parallel env-var protocol for prose actions. Actions are read by
  the agent, which already has full repo context and tool access.

## Existing state

The current contract is in
`catalog/skills/launch-work/references/project-hooks.md`. Highlights:

- Discovery from
  `<repo-root>/.agent-plugins/bento/bento/hooks/<phase>/`,
  `$XDG_CONFIG_HOME/agent-plugins/bento/bento/hooks/<phase>/`, then
  `~/.config/agent-plugins/bento/bento/hooks/<phase>/`.
- `<phase>` is `launch-work` or `land-work`.
- One injection moment per phase:
  - `launch-work` runs hooks after worktree verification, before deps.
  - `land-work` runs hooks before merge preview, rebase, or merge.
- Env vars: `BENTO_HOOK_PHASE`, `BENTO_HOOK_REPO_ROOT`, `BENTO_HOOK_BRANCH`,
  `BENTO_HOOK_BASE_REF`, `BENTO_HOOK_BASE_SHA`, `BENTO_HOOK_HEAD_SHA`,
  `BENTO_HOOK_RUNTIME`, `BENTO_HOOK_TASK_ID`, `BENTO_HOOK_REQUIRES_HUMAN=75`.
- Exit codes: `0` pass, `75` human handoff, any other non-zero failure.
- `75` chosen because it is `EX_TEMPFAIL` from BSD `sysexits.h`: "temporary
  failure; user is invited to retry." Picking from the sysexits range avoids
  collisions with shell conventions (1, 2, 126, 127, 128+N).

## Design

### Directory layout

The structure groups by skill (`launch-work`, `land-work`), then by extension
flavor (`hooks`, `actions`), then by position (`pre`, `post`). All extensions
that affect a given skill live under one subtree, so a project's customization
of `launch-work` is visible at a glance.

```
.agent-plugins/bento/bento/
├── launch-work/
│   ├── hooks/
│   │   ├── pre/     # after worktree verify, before deps install
│   │   └── post/    # after ready-to-land checkpoint, before skill returns
│   └── actions/
│       ├── pre/     # after worktree verify, before deps install
│       └── post/    # after ready-to-land, before skill returns
└── land-work/
    ├── hooks/
    │   ├── pre/     # before merge preview/rebase/merge
    │   └── post/    # after merge succeeds, before skill returns
    └── actions/
        ├── pre/     # before merge preview/rebase/merge
        └── post/    # after merge succeeds, before skill returns
```

Same XDG discovery chain as today: repo-scoped first, then
`$XDG_CONFIG_HOME/agent-plugins/bento/bento/...`, then
`~/.config/agent-plugins/bento/bento/...` when `XDG_CONFIG_HOME` is unset.

Hooks and actions share the same `pre`/`post` timings within a skill — when
both exist at the same position, hooks run first, then actions (see
"Discovery and ordering").

### Backwards compatibility

The legacy path `<…>/hooks/<phase>/<executable>` (no skill-grouped subtree, no
position subdir) is interpreted as `<phase>/hooks/pre/<executable>` — the
existing single hook moment maps onto the new `pre` slot, since `pre` fires
at exactly the same point in each skill (after worktree verify for
launch-work; before merge preview for land-work).

The discovery rules check both the new path and the legacy path. A repo with
hooks at the legacy path keeps working without changes. A one-release
deprecation note in `project-hooks.md` directs authors to move executables
into `<phase>/hooks/pre/`.

### Position semantics

| Skill | Position | Fires at | Worktree exists? | Abort effect |
|---|---|---|---|---|
| launch-work | pre | after worktree verify, before deps install | yes | full halt; worktree preserved |
| launch-work | post | after ready-to-land checkpoint, before skill returns | yes | full halt; work stays on the branch, user does not proceed to land-work |
| land-work | pre | before merge preview/rebase/merge | yes (feature) | full halt; merge has not started |
| land-work | post | after merge succeeds, before skill returns | yes (feature) | advisory only; merge stands |

"Abort" means an exit-75/non-zero (hooks) or matched stop condition (actions)
halts the skill before the next normal step. "Full halt" preserves the branch
and linked worktree and does not perform destructive cleanup. "Advisory only"
means the skill surfaces the message but does not roll anything back.

The two real motivating extensions map cleanly:

- **After launch-work executes** → `launch-work/actions/post/` (or
  `launch-work/hooks/post/` for a script).
- **Before land-work executes** → `land-work/actions/pre/` (or
  `land-work/hooks/pre/` for a script).

There is intentionally no slot before worktree creation in launch-work, nor a
slot earlier than the existing land-work timing. Adding a third position
later would be backwards-compatible if a real need surfaces.

`launch-work/post` and `land-work/pre` are the slots motivated by the two
real extensions:

- **After launch-work executes** → `actions/launch-work/post/*.md` (or
  `hooks/launch-work/post/*` for a script).
- **Before land-work executes** → `actions/land-work/pre/*.md` (or
  `hooks/land-work/pre/*` for a script).

`land-work/post` is treated as **advisory**: the merge has already happened,
so a non-zero exit or matched stop condition cannot reverse it. The skill
surfaces the message and marks itself complete-with-warnings; nothing is
unwound. This is documented in the contract so authors don't write
"veto a completed merge" expectations into `post/` extensions.

### Discovery and ordering

For each position slot:

1. Hooks are discovered and run **first**. If any hook exits `75` or other
   non-zero, the skill aborts at that position; **actions never load** for that
   position.
2. If all hooks at the position pass (exit 0), actions are discovered and
   applied.

#### Numeric prefix ordering convention

Hook and action filenames must begin with a two-digit decimal prefix and a
separator, e.g.:

```
10-check-lockfile.sh
20-warn-on-uncommitted-config.md
99-final-report.sh
```

The skill sorts files by ascending numeric prefix; ties (same number, e.g.
`30-foo.sh` and `30-bar.sh`) break by lexicographic filename order. The
convention mirrors `/etc/init.d` and `/etc/cron.d` — leave gaps (10, 20,
30…) so later additions can slot between existing items without renumbering.

Files that don't start with `<two-digit>-` are **ignored** with a soft
warning logged to the skill's stderr at discovery time. This is strict
enough to prevent accidental ordering surprises and lenient enough that
adding a `README.md` next to the actions doesn't break discovery.

Other discovery rules:

- Hidden files (leading dot), editor backups (trailing `~`, `.bak`,
  `.swp`), and filenames containing path separators are ignored without
  warning.
- For hooks: only regular executable files are run. Non-executable files,
  symlinks to non-existent targets, and directories are ignored.
- For actions: only files ending in `.md` are loaded. Other extensions and
  directories are ignored.

The working directory for hook execution is the **linked worktree** for
`launch-work/*` and the **feature-branch worktree** for `land-work/*`. All
positions in this design fire after the relevant worktree exists.

### Hook execution — extended env protocol

Existing variables stay. Additions and clarifications:

| Variable | Meaning |
|---|---|
| `BENTO_HOOK_PHASE` | `launch-work` or `land-work` (existing) |
| `BENTO_HOOK_POSITION` | `pre` or `post` (new) |
| `BENTO_HOOK_REPO_ROOT` | Absolute repo root (existing) |
| `BENTO_HOOK_WORKTREE` | Absolute path to the worktree (new; always set in this design) |
| `BENTO_HOOK_BRANCH` | Current task or feature branch |
| `BENTO_HOOK_BASE_REF` | Primary-branch ref name |
| `BENTO_HOOK_BASE_SHA` | SHA of base ref when known |
| `BENTO_HOOK_HEAD_SHA` | SHA of feature-branch head when known |
| `BENTO_HOOK_MERGE_SHA` | SHA of the merge commit; set only in `land-work/hooks/post` (new) |
| `BENTO_HOOK_LANDED` | `1` only in `land-work/hooks/post` once merge is complete (new) |
| `BENTO_HOOK_RUNTIME` | `claude`, `codex`, `unknown` |
| `BENTO_HOOK_TASK_ID` | Tracker item ID when available |
| `BENTO_HOOK_TTY` | `1` if stdin is a TTY, else `0` (new) |
| `BENTO_HOOK_TIMEOUT` | Seconds, or empty for no timeout (new, opt-in) |
| `BENTO_HOOK_REQUIRES_HUMAN` | `75` (existing, exposed for hook authors) |

Existing rule preserved: unavailable values are set to empty strings, not
omitted.

### Hook execution — timeouts

There is **no built-in timeout**. Interactive hooks (`gh auth login`,
`op signin`, passphrase prompts, sandbox approval flows) work without
ceremony.

Risks of no timeout, and how the contract addresses them:

- **Hook hangs in a non-interactive context (CI, scheduled agent).** Hook
  authors check `BENTO_HOOK_TTY` and return `75` to cleanly hand off to a
  human:

  ```sh
  #!/bin/sh
  if [ "$BENTO_HOOK_TTY" != "1" ]; then
    echo "This hook requires an interactive terminal."
    exit "$BENTO_HOOK_REQUIRES_HUMAN"
  fi
  exec gh auth login
  ```

- **Hung non-interactive hook (deadlock, hung subprocess) blocks the skill.**
  The agent surfaces a soft heartbeat after ~60 seconds and again
  periodically — informational only, not a kill. Ctrl-C reaches the hook
  directly because stdin is inherited.

- **Bounded run wanted for a specific repo.** Set `BENTO_HOOK_TIMEOUT=<n>`.
  Default unset means no timeout. The skill enforces the timeout via
  `subprocess.run(..., timeout=n)` (or equivalent). On timeout, the skill
  treats the result as a non-zero abort and surfaces a timeout message.

### Hook execution — exit codes

Unchanged from the existing contract:

- `0` — pass; continue.
- `75` — human handoff; halt, preserve branch and linked worktree, surface
  stdout as the handoff message, do not perform destructive cleanup.
- any other non-zero — failure; halt, surface stdout and stderr, preserve
  branch and linked worktree.

For `land-work/hooks/post` only, exit `75` and other non-zero are **advisory**:

- The merge has already happened; nothing is rolled back.
- The skill surfaces the message and marks itself complete-with-warnings.
- Tracker mutations (closing the issue, etc.) still proceed unless the hook
  message explicitly tells the user to delay them.

### Action execution

Each action file is a markdown document. The skill agent reads each file (in
lexicographic order within the directory) and applies it as additive guidance
for the rest of the position's work. Actions are *not* concatenated and
applied as one blob — they are applied in order, each one modifying the
agent's understanding before the next one is read.

**Filename:** must follow the `<two-digit>-<slug>.md` convention from the
discovery section (e.g., `30-warn-on-uncommitted-config.md`).

**Authoring shape (recommended, not enforced):**

- Optional H1 title.
- Optional `## Context` block stating what state the action assumes (e.g.,
  "assumes the linked worktree exists and the progress log is at
  `worktree-ready`").
- Body prose: additive instructions and any modifying guidance.
- Optional `## Stop conditions` section (see below).

**Stop conditions:**

The contract reserves one section name: `## Stop conditions`. If present, it
contains a markdown list of predicates. The agent evaluates each predicate at
the moment the action is applied. If any predicate matches, the agent halts,
surfaces the matched condition to the user, and preserves branch and linked
worktree (mirroring exit-75 semantics for hooks).

Predicates are free-form markdown — the agent uses its tools to verify them.
Examples:

```markdown
## Stop conditions
- The repository contains uncommitted changes outside the worktree's task
  scope. Run `git status` to verify.
- A `LICENSE.draft` file exists in the repo root.
- The current branch's parent is not the documented primary branch.
```

For `land-work/actions/post`, stop conditions are advisory only, matching
the hook-exit advisory rule.

**Constraints on actions (documented in the contract, not machine-enforced):**

- Actions are additive and may modify default behavior.
- Actions must not direct full replacement of the skill's built-in workflow.
- Actions in `pre/` slots that run before the worktree exists must be
  read-only (no file edits, no branch creation).

### Behavior with no extensions present

A repo with no `hooks/` and no `actions/` behaves identically to today. The
discovery passes find no executables and no `.md` files at any position; the
skill continues to its next normal step without remarking on the absence.

### Documentation locations

- `catalog/skills/launch-work/references/project-hooks.md` is updated to
  describe the new path layout (`<skill>/hooks/<position>/`), the
  numeric-prefix filename convention, the legacy-path fallback, and the new
  env vars (`POSITION`, `WORKTREE`, `MERGE_SHA`, `LANDED`, `TTY`, `TIMEOUT`).
- New file `catalog/skills/launch-work/references/project-actions.md`
  describes action discovery, the same numeric-prefix convention, the
  `## Stop conditions` convention, and authoring guidance.
- Both `launch-work/SKILL.md` and `land-work/SKILL.md` get updated workflow
  steps that reference `pre/` and `post/` positions and both reference files.

### Helper scripts

`launch-work-bootstrap.py`, `launch-work-verify.py`, `launch-work-log.py`,
`launch-work-discover.py`, `land-work-prepare.py`, `land-work-create-preview.py`,
`land-work-verify-lease.py`, `land-work-verify-landing.py`,
`land-work-clean-log.py` — none of these need behavioral changes for this
design. The hook/action invocation logic lives in the skill workflow text,
not in these helpers.

A small new helper, `bento-extensions-discover.py` (placement TBD between
`launch-work/scripts/` and `land-work/scripts/`, with a shared
`extensions-common.py` if duplication grows), may be useful to:

- Enumerate hooks and actions for a `(phase, position)` pair across the
  XDG chain.
- Apply the numeric-prefix sort and the exclusion rules (hidden,
  non-executable, non-md, missing prefix) consistently.
- Surface the soft warning for files that don't match the prefix convention.
- Emit JSON the skill text can iterate over.

This helper is recommended over inline `find`/`ls` because the prefix-sort
and the missing-prefix warning are easy to get subtly wrong in shell.

## Verification strategy

- Unit-style tests (shell or Python, matching repo norms) for:
  - numeric-prefix sort ordering, including ties and gaps;
  - missing-prefix soft-warning behavior;
  - the exclusion rules (hidden, backups, non-executable, non-md);
  - the legacy `hooks/<phase>/` → `<phase>/hooks/pre/` fallback.
- A scenario test that creates a no-op hook in each of the four hook
  positions and confirms each fires exactly once at the documented timing.
- A scenario test that creates an action with a `## Stop conditions` block
  in each of the four action positions and confirms the agent halts when
  the condition matches and proceeds when it does not. (May require a small
  harness; see open questions.)
- A scenario test for the `land-work/hooks/post` advisory rule: a non-zero
  exit surfaces the message but does not unwind the merge.
- A backwards-compatibility test: a legacy `hooks/launch-work/<exec>` path
  runs at the new `launch-work/hooks/pre/` timing.

## Constraints and risks

- **Action evaluation is not machine-checked.** A poorly written action can
  silently fail to halt when it should. Mitigation: keep the contract narrow
  — `## Stop conditions` is the only structured convention; everything else
  is plain prose.
- **Hook authors may rely on env vars that don't exist in some positions.**
  Mitigation: the contract states explicitly which vars are populated where,
  and unavailable vars are empty strings rather than unset.
- **Soft heartbeats during long-running interactive hooks may be confusing.**
  Mitigation: the heartbeat message names the running hook and notes that
  Ctrl-C reaches it directly.
- **No timeout means a misbehaving hook can hang the skill indefinitely.**
  Mitigation: opt-in `BENTO_HOOK_TIMEOUT`; document Ctrl-C as the universal
  escape; log heartbeats.
- **Discovery cost scales with positions.** Four hook positions + four action
  positions = eight directory scans per skill invocation, plus the legacy
  fallback. All are short-circuit (skip if directory absent). Unlikely to
  matter in practice.
- **Numeric-prefix soft warnings can be missed.** A repo author who drops a
  file into a position dir without the prefix may not notice the warning if
  it's buried in skill output. Mitigation: hook the discovery helper into
  the launch-work progress log so missing-prefix warnings show up in
  recovery context.

## Open questions

1. **Discovery helper placement.** A shared `bento-extensions-discover.py` is
   useful but lives awkwardly between the two skills. Options: place under
   `launch-work/scripts/` and have `land-work` reference it; create a new
   `catalog/skills/_shared/` directory; inline the discovery into each skill
   text. Defer to plan.
2. **Action testing harness.** Confirming an action's `## Stop conditions`
   actually halts the agent likely requires a small fixture-based runner.
   Defer specifics to plan.
3. **Heartbeat cadence.** 60s first, then 5min repeating? Configurable? Defer
   to plan.

## Migration

- **First release:** both legacy `hooks/<phase>/<exec>` and new
  `<phase>/hooks/pre/<exec>` are accepted. The contract documents the
  legacy form as deprecated. Existing executables continue to work without
  the numeric prefix during this window — the prefix is enforced only for
  files at the new path. Authors are invited to move their executables and
  add the prefix at the same time.
- **Second release:** drop the legacy-path fallback. The new path is
  required. Files without the numeric prefix are ignored with a hard
  warning. Repos that haven't migrated get a clear error message pointing
  at the contract.
- No migration is needed for new action support, since actions are net-new.

## Out of scope

- Replacing or restructuring the existing helper scripts.
- Changing the progress log format.
- Adding extension points to skills other than `launch-work` and `land-work`.
- Cross-repo extension sharing (e.g., a registry of canned hooks/actions).
- A general-purpose plugin system. This is intentionally scoped to two skills
  with stable, well-known phase boundaries.
