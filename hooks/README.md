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

- `bento` — Bash auto-approval (`PreToolUse`), worktree-permission seeding, and
  the `require-worktree` registration hook (`SessionStart`).
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
handling, TTY status, and common invalid assumptions — see
[`references/hook-environment.md`](references/hook-environment.md).
