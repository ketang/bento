# Installing Bento Plugins

`bento` publishes reusable plugins for coding agents. Today, the install flow in
this repository targets Claude Code's marketplace format.

This guide covers the end-user workflow:

1. Register the `bento` marketplace in Claude Code
2. Install one or more plugins from that marketplace
3. Update or remove plugins later
4. Optionally wire in hook scripts from this repo

## Before you start

You need:

- Claude Code with plugin marketplace support
- access to edit `~/.claude/settings.json`
- network access to GitHub so Claude Code can read `ketang/bento`

## Step 1: Register the marketplace

Add the following to `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "bento": {
      "source": {
        "source": "github",
        "repo": "ketang/bento"
      }
    }
  }
}
```

This makes the Bento marketplace visible to Claude Code. Registration does not
install any plugins by itself.

## Step 2: Choose a plugin

The marketplace currently publishes these plugins:

- `bento-all` for the full Bento skill pack
- `trackers` for tracker-oriented workflows such as Beads and GitHub Issues
- `stacks` for stack-specific engineering skills

If you are unsure, start with `bento-all`.

## Step 3: Install a plugin in Claude Code

After registering the marketplace, use Claude Code's plugin install command.

Examples:

```text
/install-plugin bento/bento-all
/install-plugin bento/trackers
/install-plugin bento/stacks
```

Use one command per plugin you want to install.

## Step 4: Verify the install

After installation, Claude Code should show the plugin as installed and make
its packaged skills available for invocation according to Claude Code's normal
plugin behavior.

If Claude Code cannot find the marketplace or plugin:

- confirm that `~/.claude/settings.json` is valid JSON
- confirm the marketplace key is named `bento`
- confirm you used the `bento/<plugin-name>` form in `/install-plugin`
- confirm Claude Code can reach GitHub

## Updating a plugin

Use Claude Code's normal plugin update or reinstall flow for the same plugin
name after new versions are published from this repository.

If your Claude Code setup does not expose a dedicated update command, reinstall
the plugin by name:

```text
/install-plugin bento/bento-all
```

Use the same pattern for `trackers` or `stacks`.

## Removing a plugin

Use Claude Code's normal plugin removal flow for the installed plugin name.

If your Claude Code setup expects an explicit plugin identifier, use the same
`bento/<plugin-name>` name you used during installation.

## Hooks are separate

Hook scripts in this repository are not installed through the plugin system.
They must be wired manually in `~/.claude/settings.json`.

See [hooks/README.md](/home/ketan/project/bento/.claude/worktrees/install-doc/hooks/README.md)
for hook wiring examples.

## For maintainers

This guide is for end users installing published plugins.

If you are changing the canonical skill content in this repository, edit
`catalog/skills/` and rebuild generated plugins with `scripts/build-plugins`.
