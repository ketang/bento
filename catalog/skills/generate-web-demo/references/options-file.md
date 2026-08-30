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
    "queueFile": null
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

The default warning queue location is `demo-warnings.jsonl` inside the
per-run artifact directory (see `references/artifacts.md`); `queueFile: null`
means "use that default." Set `queueFile` to an explicit path to override the
default with a fixed location, such as `.demo-warnings.jsonl` at the repo
root, when a repo wants one stable queue file that persists across runs
instead of a fresh file per run. This is an override, not a second default.

Treat missing options as bundled defaults, not as an error. Treat invalid
options as a warning record and continue with safe defaults whenever possible.
