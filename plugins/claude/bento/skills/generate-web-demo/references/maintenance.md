# Maintenance

Document that the demo must be reviewed when these change:

- user-facing product flows
- routes, navigation, or page layout that the demo traverses
- accessible names, labels, roles, or selectors used by tests
- seed/demo data and auth/session setup
- app startup, ports, environment variables, or container topology
- functional tests that overlap with the walkthrough
- screenshot artifact layout
- warning queue schema or queue processing instructions

Prefer shared helpers between functional Playwright tests and the demo for
login, seeding, navigation, and stable selectors. Do not make the demo depend
on brittle visual coordinates when accessible roles or app-level test helpers
are available.

When behavior changes, use the `maintain-web-demo` skill to update the
walkthrough contract instead of letting screenshots and warning queues drift.
