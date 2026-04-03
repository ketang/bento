# Installing Bento Plugins

`bento` publishes reusable plugins for coding agents. This repository generates
plugin packaging for Claude Code and OpenAI Codex.

This guide covers the end-user workflow:

1. Add the `bento` marketplace in Claude Code
2. Install one or more plugins from that marketplace
3. Find the generated Codex plugin artifacts in this repo
4. Update or remove plugins later
5. Optionally wire in hook scripts from this repo

## Before you start

You need:

- Claude Code with plugin marketplace support
- network access to GitHub so Claude Code can read `ketang/bento`

## Step 1: Add the marketplace

From within Claude Code, run:

```text
/plugin marketplace add ketang/bento
```

This adds the Bento marketplace to Claude Code so you can browse and install
its plugins. Adding the marketplace does not install any plugins by itself.

## Step 2: Choose a plugin

The marketplace currently publishes these plugins:

- `bento-all` for the full Bento skill pack
- `trackers` for tracker-oriented workflows such as Beads and GitHub Issues
- `stacks` for stack-specific engineering skills

If you are unsure, start with `bento-all`.

## Step 3: Install a plugin in Claude Code

After adding the marketplace, use Claude Code's plugin install command.

Examples:

```text
/plugin install bento-all@bento
/plugin install trackers@bento
/plugin install stacks@bento
```

Use one command per plugin you want to install.

## Step 4: Verify the install

After installation, Claude Code should show the plugin as installed and make
its packaged skills available for invocation according to Claude Code's normal
plugin behavior.

If Claude Code cannot find the marketplace or plugin:

- confirm you ran `/plugin marketplace add ketang/bento`
- confirm you used the `<plugin-name>@bento` form with `/plugin install`
- confirm Claude Code can reach GitHub

## Using Bento In Codex

Bento provides two Codex installers:

- home-scoped: available from every project on the machine
- project-scoped: only available inside one repository

Both installers download the published plugin bundles from GitHub, install the
three Bento plugins, create a timestamped backup before editing any existing
marketplace file, and safely merge only the Bento entries.

### Home-scoped install

This installs Bento under `~/plugins/` and updates
`~/.agents/plugins/marketplace.json`.

```bash
curl -fsSL https://raw.githubusercontent.com/ketang/bento/main/install/codex-home.sh | bash
```

After the script finishes, restart Codex if it is already running. The Bento
plugins will then appear under `/plugins` from any project.

### Project-scoped install

This installs Bento under `./plugins/` in the current repository and updates
`./.agents/plugins/marketplace.json`.

Run this from the project root where you want Bento available:

```bash
curl -fsSL https://raw.githubusercontent.com/ketang/bento/main/install/codex-project.sh | bash
```

After the script finishes, restart Codex if it is already running, then launch
Codex from that same project root to use the installed Bento marketplace.

### Updating a Codex install

Rerun the same installer command for the scope you want to refresh. It replaces
the Bento plugin bundles for that scope with the current published versions
from GitHub and refreshes the Bento entries in the corresponding marketplace
file.

### Codex packaging artifacts

For reference, this repository generates the following Codex artifacts when
`scripts/build-plugins` is run:

- `plugins/<plugin-name>/.codex-plugin/plugin.json`
- `plugins/<plugin-name>/assets/icon.png`
- `plugins/<plugin-name>/assets/logo.png`
- `plugins/<plugin-name>/assets/screenshot-1.png`
- `plugins/<plugin-name>/assets/screenshot-2.png`
- `plugins/<plugin-name>/assets/screenshot-3.png`

## Updating a plugin

Use Claude Code's normal plugin update or reinstall flow for the same plugin
name after new versions are published from this repository.

If your Claude Code setup does not expose a dedicated update command, reinstall
the plugin by name:

```text
/plugin install bento-all@bento
```

Use the same pattern for `trackers` or `stacks`.

## Removing a plugin

Use Claude Code's normal plugin removal flow for the installed plugin name.

If Claude Code expects an explicit marketplace-qualified plugin identifier, use
the same `<plugin-name>@bento` name you used during installation:

```text
/plugin uninstall bento-all@bento
```

## Hooks are separate

Hook scripts in this repository are not installed through the plugin system.
They must be wired manually in `~/.claude/settings.json`.

See [hooks/README.md](../hooks/README.md)
for hook wiring examples.

## For maintainers

This guide is for end users installing published plugins.

If you are changing the canonical skill content in this repository, edit
`catalog/skills/` and rebuild generated plugins with `scripts/build-plugins`.
When changing the Codex installers or installation docs, do that work from a
feature branch or a worktree rather than directly on `main`, then merge once
the installer flow has been verified.
The published installer consumes the generated `plugins/` directories directly
from GitHub and synthesizes the user's home-scoped marketplace entries during
install, so the generated plugin bundles under `plugins/` must be committed
before users can install the updated plugin set.
