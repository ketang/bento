## Claude Code Requirements

Launch teammates with Claude Code's managed team flow:

- Create a team with `TeamCreate`.
- Create one task per approved work item with `TaskCreate`.
- Start each teammate with `Agent`, setting both `team_name` and a descriptive
  `name`.

When the last Claude Code teammate in the batch is done, delete the team.
