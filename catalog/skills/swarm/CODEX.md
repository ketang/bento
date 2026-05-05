## Codex Requirements

Launch teammates with Codex sub-agents:

- Use `spawn_agent` for each approved work item.
- Use `send_input` when a running teammate needs additional instruction.
- Use `wait_agent` sparingly, only when the next critical-path step is blocked
  on the result.
- Use `close_agent` when a teammate's task is landed or explicitly deferred.
