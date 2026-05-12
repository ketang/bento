# Artifacts

Use one run directory per demo execution unless the repo already has a stable
artifact convention.

Recommended layout:

```text
tmp/demo/<timestamp-or-run-id>/
├── logs/
│   └── demo.log
├── screenshots/
│   ├── 01-open-dashboard.png
│   ├── 02-create-project.png
│   └── 03-create-project-warning.png
├── metadata.json
└── warnings.jsonl
```

Keep artifact paths stable enough for Bugshot or other review tools to ingest.
Use descriptive slugs and zero-padded step numbers so humans can scan the
sequence.

Default screenshots should exclude the visible controller overlay. If a
controller bug must be diagnosed, add an explicit diagnostic option to include
it.

`metadata.json` should record the command, browser, headed/headless state,
base URL, git SHA when available, start/end times, and summary counts for
steps, warnings, and errors.
