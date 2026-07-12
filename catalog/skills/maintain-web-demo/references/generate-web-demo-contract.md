# Generate Web Demo Contract

An existing demo created or maintained by Bento should provide:

- one canonical browser scenario
- visible and headless execution of the same scenario
- named steps with assertions
- per-step screenshots
- deterministic startup and seed/reset behavior
- a project-native command such as `make demo`
- artifact output containing logs, screenshots, metadata, and warning queue
- warning queue emission unless explicitly disabled by options
- visible-run controller support when the browser is headed

When this contract drifts, update the demo rather than forking a new harness.

## Warning-queue tracker lifecycle

When repository instructions file tracker work from queue entries, the
scaffolded contract must:

- match queued failures by failure identity (step id + failure signature), not
  by title
- search ALL issues, open and closed
- reopen a matching closed issue on recurrence instead of filing a duplicate
- require a pasted passing run over the affected step ids before closing

Older installed contracts that match only "open or in-progress" issues are
drifted and must be migrated to these rules.
