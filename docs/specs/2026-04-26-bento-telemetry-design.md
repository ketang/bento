# Bento Telemetry Design

**Date:** 2026-04-26

## Goal

Track failure rates and capture user feedback for bento skills' helper scripts. Two error modes drive the design:

- **Skill couldn't find its script** — `argv[0]` doesn't resolve, or the file isn't executable.
- **Skill ran but errored** — the script ran and exited nonzero, was interrupted, or hit a runtime exception.

Plus a structured user-feedback channel.

## Scope (v1) and Aspiration (v2)

- **v1 — local-first.** Personal feedback loop. JSONL on disk. No upload.
- **v2 — opt-in remote.** Aspiration. Schema designed so v1 logs ship cleanly through a future `bento-telemetry export` step.

## Architecture

Six components owned by bento:

1. **Hook** — `catalog/hooks/telemetry/scripts/telemetry-record.py`, wired as `PostToolUse(Bash)` in a new `telemetry` plugin's `hooks.json`. Reads stdin (`tool_input`, `tool_response`); classifies, redacts, and appends one JSONL record. Always exits 0.
2. **Local store** — `${XDG_STATE_HOME:-$HOME/.local/state}/bento/telemetry/YYYY-MM-DD.jsonl`. Append-only. UTC-dated. Lazy-created.
3. **CLI** — `scripts/bento-telemetry`, stdlib Python. Subcommands `summarize`, `tail`, `report`, `path`, `export` (stub).
4. **Skill `bento-telemetry`** — wraps `summarize` / `tail`. Look-back queries.
5. **Skill `bentobug`** — wraps `report`. Invoked as `/bentobug [<note>]` for fast capture.
6. **Future shipper hook** — `bento-telemetry export` subcommand reserved. Out of scope for v1.

Following the existing bento pattern (hook plugins separate from skill plugins; e.g. `bento_auto_allow/` is hook-only, `closure/` is skill-only), three new plugins generated:

- `telemetry` (hook only)
- `bento_telemetry` (skill only)
- `bentobug` (skill only)

The shared `scripts/bento-telemetry` CLI lives at the repo root, reused by hook (for redaction/classification helpers) and both skills.

## Capture mechanism — Approach A (chosen)

PostToolUse(Bash) hook. Realpaths `argv[0]` from the command. Records when `argv[0]` resolves under one of two known layouts:

- **Cache install**: `<marketplace_root>/<plugin>/<version>/skills/<skill>/scripts/<file>`. `<marketplace_root>` is found by walking parents of `${CLAUDE_PLUGIN_ROOT}` until the parent's basename is `cache`.
- **Dev install**: `*/catalog/skills/<skill>/scripts/<file>` — for when iterating on bento itself out of a checkout.

If `argv[0]` doesn't realpath under either layout, the hook records nothing.

**Known false-negative**: scripts copied to unconventional paths, or invoked indirectly (e.g., `python3 -m`), won't attribute. Acceptable for v1.

**Why Approach A over alternatives**:

- **B (in-script wrapper library)**: can't catch "script not found" — exactly the case the user cares most about. The script never runs, so it can't log itself.
- **C (hook + wrapper)**: YAGNI. Wrapper duplicates what the hook already gets.

The hook always exits 0 — telemetry never breaks a session. Internal failures log to `${XDG_STATE_HOME}/bento/telemetry/_hook-errors.log` so they don't pollute the data stream.

## Schema

### `script` event — one per Bash call to a watched script

```json
{
  "v": 1,
  "kind": "script",
  "id": "<uuid4>",
  "ts": "2026-04-26T17:13:42.812Z",
  "session_id": "<from ~/.claude/session_id>",
  "marketplace": "bento",
  "plugin": "land_work",
  "skill": "land-work",
  "script": "land-work-prepare.py",
  "argv_redacted": ["--apply", "--base", "main"],
  "exit": 1,
  "class": "error",
  "interrupted": false,
  "duration_ms": 1834,
  "stderr_tail": ["…", "Traceback…", "ValueError: …"]
}
```

### `user_report` event — one per `bento-telemetry report` invocation

```json
{
  "v": 1,
  "kind": "user_report",
  "id": "<uuid4>",
  "ts": "2026-04-26T17:14:01Z",
  "session_id": "<from ~/.claude/session_id>",
  "skill": "land-work",
  "context_event_ids": ["<id>", "<id>"],
  "note": "land-work used a stale base ref"
}
```

### Classification

- `ok` — exit 0, not interrupted.
- `not_found` — exit 126/127 plus stderr matching `No such file or directory` / `command not found` / `Permission denied` against `argv[0]`.
- `error` — any other nonzero exit.

`interrupted` is a separate boolean. An interrupted run is still `error`.

### Redaction — two-tier

**Write-time** — applied to every record on disk:

- `stderr_tail`: last 20 lines, capped at 4 KB total. `$HOME` prefix → `~`. `/tmp/claude-session-<id>/` → `<scratch>/`.
- `argv_redacted`: token list, no shell quoting. No further scrubbing — local file, user owns the machine.
- No stdout captured. (Bento scripts use stdout for structured JSON the model consumes; capturing it is high-volume and low-signal for failure analysis.)

**Ship-time** — applied only inside the future `bento-telemetry export` (v2):

- argv tokens reclassified: flags preserved; path-shaped → `<path>`; ref-shaped → `<ref>`; otherwise → `<value>`.
- `session_id` → short salted hash.
- `stderr_tail` further scrubbed for absolute paths, emails, URL-shaped tokens.
- Structural fields (`marketplace`/`plugin`/`skill`/`script`/`exit`/`class`/`duration_ms`/`ts`) survive unchanged.

Split keeps the local file legible for the user while making export a pure JSONL→JSONL transform later.

## CLI — `scripts/bento-telemetry`

| Subcommand | Behavior |
|---|---|
| `summarize [--since 7d] [--skill X] [--plugin Y] [--class error] [--session <id>] [--json]` | Aggregates JSONL into counts per (skill, script, class). Default text table; `--json` for machine output. |
| `tail [-n 20] [--skill X] [--session <id>]` | Most recent N records, raw JSONL. |
| `report [--skill X] [--note "..."] [--context-events auto\|<id>,<id>,...] [--session <id>]` | Captures a `user_report` record. With no `--note`, reads from stdin. `--context-events auto` (default) attaches every `error`/`not_found` event from the current session. Pass an explicit comma-separated id list to override. |
| `path` | Prints JSONL store root. |
| `export` | Stub — exits 2 with "not implemented". Reserved for the future opt-in shipper. |

Default `--session` = `~/.claude/session_id` if present; falls back to "all sessions" for `summarize`/`tail`.

Sample `summarize` output:

```
skill          script                 ok  err  nf  err%
land-work      land-work-prepare       12   3   0  20.0
launch-work    launch-work-bootstrap    8   0   1  11.1
swarm          swarm-triage             4   1   0  20.0
```

`err%` = `(error + not_found) / total`.

## Skills

### `bento-telemetry` — look-back

`recommended_model: low`.

Trigger phrases the description matches:

- Word `bento` + `telemetry|error rate|flaky|failing|broken|how often`.
- Any catalog skill name + reliability inquiry: `flaky|failing|broken|misfired|wrong|errored|how often does X fail`.
- Standalone: `error rate`, `has it been failing`.

Body: short instructions to pick the right `summarize`/`tail` filters and surface results. Counter-signal guardrail: the body explicitly tells Claude **not** to fire on bare skill-name mentions in normal directives like "use launch-work to start the task."

### `bentobug` — capture

`recommended_model: low`.

Trigger phrases:

- `/bentobug [<note>]` invocation.
- Word `bento` + `bug|report|file|capture|misfired|broken`.
- Any catalog skill name + `bug|report|broken|misfired|errored|wrong`.
- Standalone: `report this`, `file a bug`.

Body, in sequence:

1. Run `scripts/bento-telemetry tail -n 10 --session current`.
2. Identify recent `error`/`not_found` events; infer the affected skill from the most recent one.
3. If `$ARGUMENTS` is non-empty, treat it as the note. Otherwise prompt the user.
4. Run `scripts/bento-telemetry report --skill <inferred> --note "<note>" --context-events <ids>`.
5. Echo the resulting `user_report` JSON (id, skill, context_event_ids).

Counter-signal guardrail: same as `bento-telemetry`. If multiple skills with errors are present, ask the user to disambiguate before filing.

### Why two skills, not one

Each skill has a single sharp purpose. `/bentobug` is short and memorable for the most common quick-capture path; `/bento-telemetry` is the look-back path. Splitting matches bento's existing pattern of one skill per slash invocation (`/closure`, `/swarm`, `/handoff`).

## Storage / wiring / build

- Storage path: `${XDG_STATE_HOME:-$HOME/.local/state}/bento/telemetry/YYYY-MM-DD.jsonl`. Group-readable; not world-readable.
- Rotation: none in v1. User can `rm` files manually. `prune --keep 90d` is a deferrable v2 subcommand.
- `scripts/build-plugins` learns three new outputs (`telemetry`, `bento_telemetry`, `bentobug` plugins) and one injection step: each look-back/capture skill's description and body get the current catalog skill-name list inserted from `catalog/skills/`. A unit test asserts the generated description includes every name under `catalog/skills/`.

## Tests required before merge

- **Hook attribution**: scripts under cache layout, dev layout, and unrelated paths each produce the right (or no) record.
- **Classification**: synthetic exit codes 0 / 126 / 127 / 1 / interrupted produce the right `class` and `interrupted` fields.
- **Redaction (write-time)**: stderr containing `$HOME` and `/tmp/claude-session-<id>/` is rewritten correctly; `argv_redacted` preserves tokens unmodified.
- **CLI `summarize`**: aggregates correctly across multiple days; filters work; `--json` matches the documented schema.
- **CLI `report`**: writes a well-formed `user_report` linked to the requested context event IDs.
- **Build**: generated `bento-telemetry` and `bentobug` SKILL.md descriptions list every name under `catalog/skills/`.

## Out of scope for v1

- The opt-in remote shipper itself (consent prompt, endpoint config, retries). `export` is a stub.
- Tracker integration from `/bentobug` (drop a beads/GitHub issue tied to `user_report.id`).
- Auto-prompting the user for a report when a script errors. Capture remains user-initiated.
- Capturing stdout.
- Auto-pruning old JSONL files.
- Capturing skill-prose-only fallbacks (cases where Claude reads a SKILL.md but doesn't run any helper script). Out of scope because there's no Bash event to hook on.

## Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Audience | Personal v1; opt-in others v2 | No other users today; aspirational expansion |
| Capture | PostToolUse(Bash) hook | Catches both find and runtime errors without per-script changes |
| Scope | Bento-only events; schema reserves `plugin`/`marketplace` | One config flip enables broader capture later |
| Read-back | CLI + `bento-telemetry` skill | Skill enables Claude self-introspection mid-session |
| Capture surface | `bentobug` skill | Sharp single-purpose skill; matches bento's `/closure`, `/swarm` pattern |
| Storage | XDG state, JSONL, UTC-dated | Standard, append-only, easy to inspect with stdlib tools |
| Redaction | Write-time light, ship-time strict | Keep local data legible; defer scrubbing complexity to ship pipeline |
