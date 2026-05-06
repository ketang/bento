## Claude Code Requirements

In Claude Code, manually scripted deletion loops and compound `Bash` commands
can trigger "Unhandled node type" rendering errors. Keep cleanup commands as
single helper invocations or one shell step per tool call.
