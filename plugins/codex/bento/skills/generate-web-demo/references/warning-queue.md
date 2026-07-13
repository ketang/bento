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
- `stepId` a stable identifier for the failing step, distinct from the
  human-readable `step` label, so failures keep a durable identity across runs
- `failedSteps` the list of affected step ids when one root cause breaks many
- `command` for the command that produced the run

Warn-only runs should continue after a step failure when the remaining
screenshots can still teach the operator something. Deduplicate repeated root
causes before filing tracker work; do not create one issue per screenshot when
one missing control breaks many steps.

## Matching queue entries to tracker work

When repository instructions direct agents to file tracker work from queue
entries, the contract they scaffold (for example in `AGENTS.md`) must follow
these rules. Demo failures are dominated by recurring flaky or
regression-prone steps, so matching only against currently-open work re-files
duplicates of bugs that were fixed once and regressed.

1. **Match by failure identity, not title.** The identity of a queued failure
   is its step id (`stepId`, or the `failedSteps` ids) plus a failure signature
   (`dedupeKey` or the normalized failure text) — never the human-readable
   title alone. Titles drift between runs; step ids and signatures do not.
   `stepId`/`failedSteps`/`dedupeKey` are Recommended, not Required — if a
   queue entry omits all three, fall back to the required `step` field plus
   the normalized `message` text as the identity, and note in the filed issue
   that the match is lower-confidence than a `stepId`/`dedupeKey` match.

2. **Search ALL tracker issues, open and closed.** Match the queued failure
   against every issue with the same failure identity regardless of status —
   open, in-progress, AND closed. Do not restrict the search to open or
   in-progress work.

3. **Reopen on recurrence; do not re-file.** If the match is a closed issue,
   reopen it and append the new run's evidence (timestamp, screenshot, log,
   affected step ids) noting the recurrence. This keeps the original diagnosis
   and prior fix connected to the live regression. Only create a new issue when
   no open or closed issue shares the failure identity.

4. **Require a pasted passing run to close.** Closing one of these issues
   requires pasting a passing run that covers the affected step ids (the queue
   entry's `failedSteps`/`stepId`), not "fixed it" prose. Recurrence proves
   prose-only closes are unreliable for demo failures; the passing run is the
   evidence that the affected steps now succeed.

### Worked example: closed issue that regressed

A demo run queues a failure on step `inventory-picker-add-from-trip` with the
signature "packing-item-passport not visible (timeout)". An issue for that exact
step-and-signature was filed and later closed after a fix. Months later the same
step times out again and the demo re-queues it.

- **Wrong:** the agent searches only open/in-progress issues, finds none, and
  files a brand-new bug. The closed issue's diagnosis and prior fix are now
  disconnected from the live recurrence, and there are two issues for one
  failure.
- **Right:** the agent matches the queued failure identity against all issues,
  finds the closed issue with the same step id and signature, and reopens it
  with the new run's evidence. It stays closed only after a pasted passing run
  exercises `inventory-picker-add-from-trip` successfully.

Never let queue-writing bugs break the demo. If queue emission itself fails,
print a warning and continue with the original demo result.
