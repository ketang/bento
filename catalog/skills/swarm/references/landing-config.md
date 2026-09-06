# swarm-config.json: `landing` Block

Opt-in per-repo configuration for swarm's batch-landing behavior, discovered
and validated by `swarm-discover.py`. Consuming the config (persistent
integration worktrees, batch assembly, the queue/linger loop) is out of scope
for this document — see the batched-swarm-landing epic for those pieces. This
document only covers what `swarm-discover.py` parses, validates, and reports.

## Location

The `landing` key lives inside the same `swarm-config.json` file `swarm-discover.py`
already discovers (repo root, or `.claude/swarm-config.json` /
`.codex/swarm-config.json` for runtime-specific overrides).

## Schema

```json
{
  "landing": {
    "mode": "serial",
    "full_gate": "make gate",
    "gate_scope": "scripts/gate-scope.sh",
    "batch_boundary_paths": ["api/migrations/**", "api/Cargo.toml"],
    "max_batch_size": 5,
    "linger_minutes": 5,
    "integration_worktree": "~/.local/share/worktrees/<repo>/integration"
  }
}
```

| Field                  | Type          | Default    | Notes                                                                 |
|------------------------|---------------|------------|------------------------------------------------------------------------|
| `mode`                 | `serial` \| `batch` | `serial` | `batch` opts into the queue/linger landing model.                    |
| `full_gate`            | string        | `null`     | The repo's full gate command. Required for `mode: batch`.            |
| `gate_scope`           | string        | `null`     | Command that emits scoped gate commands for a diff. Required for `mode: batch`; must resolve to an executable (a repo-relative/absolute path, or a command on `PATH`). |
| `batch_boundary_paths` | list of strings (globs) | `[]` | Paths that flush and land alone under a full gate.       |
| `max_batch_size`       | positive integer | `5`     | Upper bound on branches per batch.                                    |
| `linger_minutes`       | non-negative number | `5` | Linger window before assembling a batch.                              |
| `integration_worktree` | string (path) | `null`     | Tilde-expanded on read. Usable independently of `mode` — a serial-mode repo can still declare a persistent integration worktree. |

Every field is optional; an absent `landing` key (or one that is not a JSON
object) reports `landing: null` with a warning for the latter case.

## Fail-Safe Validation

`swarm-discover.py` never fails open into weaker gating. There are two classes
of validation failure:

1. **Gate-strength failures** — `mode: batch` with a missing or empty
   `full_gate`, a missing `gate_scope`, or a `gate_scope` that does not
   resolve to an executable command. Any of these degrade the **entire**
   `landing.mode` to `serial`, with a warning naming the problem. This is
   deliberate: a batch config that cannot actually run its scoped gates must
   not silently run as an under-gated batch.
2. **Tuning-field failures** — a malformed `batch_boundary_paths` (not a list
   of strings), `max_batch_size` (not a positive integer), `linger_minutes`
   (not a non-negative number), or `integration_worktree` (not a non-empty
   string). Each of these falls back independently to its documented default
   with its own warning; they do not force `mode` down to `serial`, since
   they do not affect how strong the gate is.

Every degradation is reported in `swarm-discover.py`'s `warnings` array, never
silently.

## Output

`swarm-discover.py`'s JSON output's `landing` key is either `null` (no usable
config) or the fully-normalized object with every field above present (schema
defaults filled in, `integration_worktree` tilde-expanded).
