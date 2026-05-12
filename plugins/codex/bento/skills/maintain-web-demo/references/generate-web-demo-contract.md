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
