# Options File

Use the `agent-plugins` convention for user-editable demo settings:

```text
<repo>/.agent-plugins/bento/bento/generate-web-demo/options.json
$XDG_CONFIG_HOME/agent-plugins/bento/bento/generate-web-demo/options.json
~/.config/agent-plugins/bento/bento/generate-web-demo/options.json
```

Resolve per file in repo, home, bundled-default order. Do not invent another
configuration location.

## Baseline Schema

Use JSON unless the repo has a strong existing config convention.

```json
{
  "warnings": {
    "enabled": true,
    "queueFile": ".demo-warnings.jsonl"
  },
  "screenshots": {
    "enabled": true,
    "includeController": false,
    "onFailure": true
  },
  "visible": {
    "controller": true,
    "pauseAtStart": false,
    "defaultDelayMs": 0
  },
  "artifacts": {
    "directory": "tmp/demo"
  }
}
```

The warning queue is part of the demo design. `warnings.enabled: false` only
disables emission for a user or repo that explicitly opts out.

Treat missing options as bundled defaults, not as an error. Treat invalid
options as a warning record and continue with safe defaults whenever possible.
