# Hooks

Generated plugin lifecycle hooks are sourced from `catalog/hooks/`, not this
top-level directory.

## Platform Peer Layout

Use one peer source per runtime:

```text
catalog/hooks/<hook-name>/
├── claude/
│   ├── hooks.json
│   └── scripts/
└── codex/
    ├── hooks.json
    └── scripts/
```

`scripts/build-plugins` copies only the peer source for the generated platform
into `plugins/<platform>/<plugin>/hooks/`. A hook with no platform peer source
is not materialized for that runtime.

Use separate peer implementations when hook protocols differ. For example,
Claude Bash auto-approval is implemented as a `PreToolUse` permission decision,
while Codex uses `PermissionRequest` with Codex's decision shape.

## Available catalog hooks

- `bento` — Bash auto-approval (`PreToolUse`), worktree-permission seeding, the
  `require-worktree` registration hook (which also registers a `require-
  worktree-git-guard` `PreToolUse`/`Bash` hook — see below), and the
  `agent-env-doctor` (`SessionStart`). The doctor is advisory and non-blocking: on session start it
  scans the repo for agent wiring that is silently broken — dangling/empty
  `@import`s in `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`, registered hook commands
  whose binary is missing, dormant installed plugins, unrecognized
  `.agent-mode.local` tokens, a bare primary checkout that still has a working
  tree, prunable git worktrees, stale `/tmp/land-work-preview-*` directories
  and unregistered directories under `~/.local/share/worktrees/<repo>/`, and
  (when `.beads/` exists) an orphaned dolt sql-server holding the beads DB lock
  — and injects warning lines into session context. It never blocks (always
  exits 0) and is suppressed per repo by adding `agent_env_doctor=false` to
  `.agent-mode.local` (the same file and mechanism the `require-worktree` and
  `hygiene` hooks use). To silence the dormant-plugin nudge for one
  inapplicable plugin without disabling any other check, add
  `agent_env_doctor_skip_plugin=<name>[,<name>...]` instead; the stale-preview
  threshold (default 24h) is overridable with
  `agent_env_doctor_preview_max_age_hours=<hours>`.

  The dormant-plugin nudge has a decision path instead of repeating in full
  every session (bento-rdtn.2): the first sighting of a given dormant plugin
  in a repo prints the full nudge plus three options (wire it now, skip
  permanently, or remind later), and writes `agent_env_doctor_seen=<plugin>
  [,<plugin>...]` to `.agent-mode.local`. Every later session then collapses
  that plugin's nudge to one line — `<plugin> dormant — decision pending, see
  .agent-mode.local` — until an actual decision (`agent_env_doctor_skip_plugin`
  or `agent_env_doctor_remind_after`) is recorded. `agent_env_doctor_remind_after=
  <plugin>:<YYYY-MM-DD>[,<plugin>:<YYYY-MM-DD>...]` fully suppresses that
  plugin's nudge until the given date, then shows the full form once more
  (and clears the entry, folding the plugin into `agent_env_doctor_seen` so
  it collapses again afterward) rather than repeating forever. A Codex peer runs every
  check except the hook-binary and dormant-plugin checks, which are
  Claude-only (they read `.claude/settings.json` and the Claude plugin
  registry, which Codex has neither of).
  `.agent-mode.local` has two owners sharing one file: Bento's own
  `key=value` settings above, and dotfiles' `bashrc.agent-mode.sh` shell
  launcher, which owns a bare `dangerous` token, a quoted `mode = "..."`
  assignment, and an optional `tools = [...]` assignment (these enable
  `--dangerously-skip-permissions` / `--dangerously-bypass-approvals-and-sandbox`
  at process launch, outside of any hook). The doctor recognizes both
  grammars in the same file and only flags lines that match neither.

  `require-worktree-git-guard` (registered by the same `register-require-
  worktree-hook.py` SessionStart hook, under `PreToolUse`/`Bash`) is a
  mechanical backstop for the "never mutate outside land-work" doctrine
  (bento-rdtn.15): it blocks (exit 2) `git merge`/`rebase`/`reset`/`clean`,
  `git checkout <primary-branch>`, `git branch -D <primary-branch>`, and
  `git push --force*` whenever the Bash command's cwd resolves to the
  **primary checkout** (never a linked worktree) — so this doesn't depend on
  the Bash permission allowlist, which is friction control, not policy.
  Independently of checkout, it also blocks `--no-verify` and a `-c
  core.hooksPath=...`/`--config core.hooksPath=...` override on any git
  invocation, since both silently skip hooks. A command containing the
  literal marker `BENTO_LAND_WORK=1` is treated as an authorized land-work/
  launch-work operation and skipped entirely — `land-work/scripts/land.py`
  and the individual `land-work-*.py` scripts never need it themselves (their
  git mutations run as internal subprocess calls, never as a separate Bash
  tool call), so this is only for a raw git command that genuinely must run
  outside those scripts. Add `require_worktree=false` to `.agent-mode.local`
  to disable the primary-checkout mutation rule for a repo (the same switch
  `require-worktree.sh` uses); add `hook_bypass=allow` to disable the
  `--no-verify`/`core.hooksPath` rule specifically. Like `require-
  worktree.sh`, this is a regex/token-level guard over the command string,
  not a full shell parser — it fails open (never blocks) on any git or parse
  error.
- `session-id` — persists the Claude Code session id and a per-session scratch
  directory (`SessionStart`).
- `telemetry` — opt-in Bash telemetry capture.
- `hygiene` — working-tree hygiene (`SessionStart` + `Stop`). The SessionStart
  hook snapshots the repo's untracked files to
  `<XDG_CACHE_HOME or ~/.cache>/bento/hygiene-baseline-<session_id>.txt`; the
  Stop hook diffs the current tree against that baseline and emits a loud,
  advisory `block` decision listing any new untracked files not covered by
  `.gitignore`. It never deletes anything, stays silent when the tree is
  unchanged or no baseline exists, and is suppressed per repo by adding
  `hygiene_check=false` to `.agent-mode.local` (the same file and mechanism the
  `require-worktree` hook uses for `require_worktree=false`).

## Hook contract

For exit-code and JSON-decision semantics — what blocks, what allows, and the
common mistake of using `exit 1` when you meant `exit 2` — see
[`references/hook-contract.md`](references/hook-contract.md).

## Hook execution environment

For working directory, environment variable inheritance, stdin shape, stdout
handling, TTY status, and common invalid assumptions:

- Claude Code: [`references/hook-environment.md`](references/hook-environment.md)
- Codex CLI (differs materially — workspace cwd, injected vars, sandbox gates
  hook writes): [`references/codex-hook-environment.md`](references/codex-hook-environment.md)

The runtime environment above applies to **agent-runtime hooks** only. Bento
also has two lifecycle-extension mechanisms confusingly also called "hooks"
(hook scripts and hook skills for `launch-work`/`land-work`) whose environments
are entirely different. See
[`references/hook-taxonomy.md`](references/hook-taxonomy.md) to tell them apart.
