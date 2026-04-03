# Install

Install the Bento marketplace in Claude Code:

```text
/plugin marketplace add ketang/bento
```

Then install one or more plugins:

```text
/plugin install bento-all@bento
/plugin install trackers@bento
/plugin install stacks@bento
```

Reload plugins in the current session:

```text
/reload-plugins
```

If you are unsure, start with `bento-all`.

For Codex:

```bash
# Home-scoped
curl -fsSL https://raw.githubusercontent.com/ketang/bento/main/install/codex-home.sh | bash

# Project-scoped
curl -fsSL https://raw.githubusercontent.com/ketang/bento/main/install/codex-project.sh | bash
```

For the longer guide, including updates, removal, and hook wiring, see
[docs/installing-plugins.md](docs/installing-plugins.md).
