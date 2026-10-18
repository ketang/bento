## Claude Code Requirements

Launch teammates with Claude Code's managed team flow:

- Create a team with `TeamCreate`.
- Create one task per approved work item with `TaskCreate`.
- Start each teammate with `Agent`, setting `team_name`, a descriptive `name`,
  and `model: "sonnet"` by default. Make each `name` distinctive and
  unmistakable as a teammate: `swarm-<tracker-id>-<slug>` (e.g.
  `swarm-bento-9sgj-docs`). Only the lead should be reachable via Remote
  Control; a `swarm-*` session in the Claude app's Remote Control list means a
  teammate connected, so report it to the user. Override to a stronger model (e.g. `opus`)
  only when the task involves deep architectural judgment, ambiguous scope, or
  cross-cutting design decisions — note the override reason in the triage
  table's risk-notes column (Phase 1, step 4).

When the last Claude Code teammate in the batch is done, delete the team.
