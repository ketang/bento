# Install

Install the Bento marketplace in Claude Code:

```text
/plugin marketplace add ketang/bento
```

Then install one or more plugins:

```text
/plugin install bento@bento
/plugin install trackers@bento
/plugin install stacks@bento
```

The marketplace also publishes `session-id` and `hygiene` (hook-only plugins),
plus the external `bugshot` and `storystore` plugins. The authoritative list is
`.claude-plugin/marketplace.json`; see
[docs/installing-plugins.md](docs/installing-plugins.md) for what each provides.

Reload plugins in the current session:

```text
/reload-plugins
```

If you are unsure, start with `bento`.

For Codex:

```bash
# Home-scoped
curl -fsSL https://raw.githubusercontent.com/ketang/bento/main/install/codex-home.sh | bash

# Project-scoped
curl -fsSL https://raw.githubusercontent.com/ketang/bento/main/install/codex-project.sh | bash
```

Lifecycle hooks ship inside the plugins, so installing a plugin installs its
hooks — no manual `settings.json` wiring is needed.

For the longer guide, including updates, removal, and how bundled hooks install,
see [docs/installing-plugins.md](docs/installing-plugins.md).
