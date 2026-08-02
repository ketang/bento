## Codex Requirements

Launch teammates with Codex sub-agents:

- Use `spawn_agent` for each approved work item.
- Use `send_input` when a running teammate needs additional instruction.
- Use `wait_agent` sparingly, only when the next critical-path step is blocked
  on the result.
- Use `close_agent` when a teammate's task is landed or explicitly deferred.

### Teammate Model Policy

During Phase 0, run `swarm-discover.py --runtime codex`. Its
`teammate_model`, `teammate_reasoning_effort`, and `teammate_config_path`
fields resolve the optional Bento customization in this order:

1. `<repo>/.agent-plugins/bento/bento/swarm/config.json`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/swarm/config.json`, using the
   platform's normal home configuration root when XDG is unset
3. the plugin-bundled default

The configuration shape is:

```json
{
  "codex": {
    "model": "gpt-5.6-terra",
    "reasoning_effort": "high"
  }
}
```

The bundled default leaves both settings absent so Codex's normal inheritance
continues unless the user opts in.

For every `spawn_agent` call:

1. Use any model or reasoning effort from the explicit user request for this
   run.
2. Otherwise use the corresponding non-null discovery field.
3. When a field is null, omit that spawn argument; do not pass null.
4. Set `fork_turns: "none"`. The required swarm teammate prompt is
   self-contained and supplies the task, scope, risks, quality gates, row
   number, landing target, and working-hygiene rules without inheriting the
   lead's chat history.

`teammate_config_path` is provenance for diagnostics, not a spawn argument.
These settings control spawned teammates only; they do not change the model of
the already-running lead.
