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
