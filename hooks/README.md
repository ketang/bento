# Hooks

Hook scripts organized by Claude Code event type. Each event gets its own subdirectory; each concern gets its own script.

## Directory structure

```
hooks/
├── pre-tool-use/       # runs before a tool is invoked
│   └── <concern>.sh
├── post-tool-use/      # runs after a tool completes
│   └── <concern>.sh
├── stop/               # runs when the agent stops
│   └── <concern>.sh
└── README.md
```

## Wiring hooks into Claude Code

Add entries to `~/.claude/settings.json`. Multiple hooks on the same event are listed in the `hooks` array within a matcher entry:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "/path/to/bento/hooks/post-tool-use/log.sh"},
          {"type": "command", "command": "/path/to/bento/hooks/post-tool-use/audit.sh"}
        ]
      },
      {
        "matcher": "",
        "hooks": [
          {"type": "command", "command": "/path/to/bento/hooks/post-tool-use/any-tool.sh"}
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {"type": "command", "command": "/path/to/bento/hooks/pre-tool-use/guard.sh"}
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {"type": "command", "command": "/path/to/bento/hooks/stop/notify.sh"}
        ]
      }
    ]
  }
}
```

The `matcher` field filters by tool name. An empty string `""` matches all tools.

## Hook environment variables

Claude Code passes context to hooks via environment variables:

| Variable | Available in | Description |
|---|---|---|
| `CLAUDE_TOOL_NAME` | PreToolUse, PostToolUse | Name of the tool being used |
| `CLAUDE_TOOL_INPUT` | PreToolUse, PostToolUse | JSON-encoded tool input |
| `CLAUDE_TOOL_OUTPUT` | PostToolUse | JSON-encoded tool output |
| `CLAUDE_SESSION_ID` | All | Current session identifier |

## Hooks in this repo

_(none yet — add entries here as hooks are created)_
