# Warning Queue

Every generated demo should have a warning/error feedback loop. The demo writes
queue entries; repository instructions such as `AGENTS.md` may decide whether
agents inspect or file tracker work from those entries.

Prefer JSON Lines so the demo can append safely:

```json
{"timestamp":"2026-05-11T12:00:00Z","demo":"main","step":"create project","severity":"warning","message":"Save button did not become enabled","screenshot":"screenshots/04-create-project-warning.png","log":"logs/demo.log"}
```

Required fields:

- `timestamp` in UTC ISO-8601 form
- `demo` stable demo identifier
- `step` human-readable step name
- `severity`, usually `warning` or `error`
- `message` with the actionable failure text

Recommended fields:

- `screenshot` relative to the artifact directory
- `log` relative to the artifact directory
- `dedupeKey` when the runner can group many step failures into one root cause
- `command` for the command that produced the run

Warn-only runs should continue after a step failure when the remaining
screenshots can still teach the operator something. Deduplicate repeated root
causes before filing tracker work; do not create one issue per screenshot when
one missing control breaks many steps.

Never let queue-writing bugs break the demo. If queue emission itself fails,
print a warning and continue with the original demo result.
