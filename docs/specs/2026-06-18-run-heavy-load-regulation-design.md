# Load Regulation for Heavy Agent Jobs

**Date:** 2026-06-18
**Status:** Approved

## Context

When multiple agents run concurrently (via swarm or manual parallel dispatch), each
agent may invoke heavy build commands — `cargo build`, `build-plugins`, bundlers, etc.
These commands pile up CPU and memory simultaneously, occasionally triggering the OOM
killer. The problem is downstream of the agents themselves: the agents are fine, but
the jobs they spawn are not coordinated at the resource level.

## Goal

Give agents a simple, consistent way to run heavy jobs without piling on an already-
loaded machine, using two mechanisms:
1. **Wait if load is extreme** — poll before starting, back off if load is above threshold.
2. **Nice it regardless** — run every heavy job at reduced CPU and I/O priority.

## Solution

### `scripts/run-heavy`

A shell wrapper agents invoke instead of running heavy commands directly.

```
scripts/run-heavy <cmd> [args...]
```

Behavior:

1. Read 1-minute load average from `/proc/loadavg`.
2. Compare to `nproc * HEAVY_LOAD_FACTOR` (default 1.5, override via env var).
3. If load exceeds threshold, print a message, sleep 30s, retry.
4. Give up waiting after `HEAVY_MAX_WAIT` seconds (default 600) and proceed anyway.
5. Exec the command under `nice -n 10 ionice -c 3`.

Environment overrides:
- `HEAVY_LOAD_FACTOR` — multiplier on nproc (default: 1.5)
- `HEAVY_MAX_WAIT` — max seconds to wait before proceeding (default: 600)

### Skill guidance additions

**`launch-work` SKILL.md** — new "Heavy Job Protocol" subsection in the
concurrent-safe solo work section. Defines heavy jobs and instructs agents to
prefix them with `scripts/run-heavy`.

**`swarm` SKILL.md** — short callout in Phase 2 (launch teammates): teammates
should use `run-heavy` for build commands in their worktrees.

### What counts as a heavy job

Commands that invoke a compiler, linker, test runner, or bundler on a non-trivial
codebase:

- `cargo build`, `cargo test`, `cargo clippy`, `rustc`
- `scripts/build-plugins`
- `npm run build`, `pnpm build`, `webpack`, `vite build`
- `tsc --build` on large projects
- `go build ./...`, `make` (non-trivial targets)

**Not heavy:** `git`, `bd`, file reads/writes, fast unit tests, linting a handful
of files.

## Verification

1. `scripts/run-heavy echo "ok"` on idle machine → executes immediately.
2. Inflate load (`stress-ng --cpu $(nproc) &`) and run `scripts/run-heavy echo "ok"` → prints wait message, retries.
3. `ps` during a heavy job via `run-heavy` → nice value is 10.
4. Spot-check that both SKILL.md files mention the protocol.

## Files changed

- `scripts/run-heavy` (new)
- `catalog/skills/launch-work/SKILL.md` (new subsection)
- `catalog/skills/swarm/SKILL.md` (new callout in Phase 2)
- `scripts/build-plugins` rebuild after skill changes
