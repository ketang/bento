## Claude Code Requirements

Launch teammates with Claude Code's managed team flow:

- Create a team with `TeamCreate`.
- Create one task per approved work item with `TaskCreate`.
- Start each teammate with `Agent`, setting `team_name`, a descriptive `name`,
  and `model: "sonnet"` by default. Override to a stronger model only when the
  task's triage entry calls for it.

When the last Claude Code teammate in the batch is done, delete the team.
