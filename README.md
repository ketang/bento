# bento

`bento` is a plugin marketplace for coding agents.

It packages reusable agent capabilities as installable plugins and keeps
related hook scripts in the same repository. The current implementation targets
Claude Code's marketplace format, but the repo is organized around a broader
idea: versioned, composable capabilities for agentic coding workflows.

## What lives here

- agent skills packaged as reusable capabilities
- generated plugin bundles assembled from canonical skill sources
- hook scripts for agent-tooling events
- marketplace metadata for discovery and installation

## Repository model

`bento` keeps canonical skill sources under `catalog/skills/` and generates
installable plugin directories under `plugins/` with `scripts/build-plugins`.

This supports both:

- coarse-grained installs such as `bento-all`
- narrower installs such as `trackers` and `stacks`

The separation is intentional:

- `catalog/` is the source of truth
- `plugins/` is generated build output

Do not hand-edit generated plugin skill directories. Edit the canonical sources
and rebuild the plugins.

## Current target platform

Today, `bento` emits plugins in Claude Code's marketplace format. That is the
current packaging target, not the full identity of the repo.

If you are documenting or extending this project, prefer framing it as a
marketplace for coding agents first, then describe Claude Code compatibility as
the current concrete implementation.

## Register as a marketplace

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

After registering, plugins in this repo are discoverable and installable via
Claude Code's built-in plugin system.

## Canonical skill sources

Create or update skills under:

```text
catalog/skills/<skill-name>/
└── SKILL.md
```

`SKILL.md` format:

```markdown
---
name: skill-name
description: |
  When the agent should invoke this skill...
---

# Skill content here
```

## Building plugins

Run:

```bash
scripts/build-plugins
```

That script:

- materializes generated plugin directories under `plugins/`
- writes each plugin's `.claude-plugin/plugin.json`
- rebuilds the root `.claude-plugin/marketplace.json`
- removes generated plugin directories that are no longer part of the current
  plugin set

## Generated plugin format

Each generated plugin lives at `plugins/<plugin-name>/`:

```text
plugins/<plugin-name>/
├── .claude-plugin/
│   └── plugin.json
└── skills/
    └── <skill-name>/
        └── SKILL.md
```

Generated `plugin.json` format:

```json
{
  "name": "plugin-name",
  "description": "What this plugin does",
  "version": "1.0.0",
  "author": {
    "name": "Ketan Gangatirkar"
  }
}
```

The marketplace manifest is generated automatically; do not edit
`.claude-plugin/marketplace.json` by hand.

## Hooks

1. Create `hooks/<event-name>/<concern>.sh` such as `hooks/post-tool-use/log.sh`
2. Make it executable with `chmod +x hooks/post-tool-use/log.sh`
3. Wire it into `~/.claude/settings.json`

See [hooks/README.md](hooks/README.md) for the exact format.

## Structure

```text
bento/
├── catalog/        # canonical skill sources
├── .claude-plugin/ # generated marketplace metadata
├── plugins/        # generated installable plugins
├── scripts/        # repo utilities such as build-plugins
├── hooks/          # hook scripts organized by event type
├── AGENTS.md       # agent-facing guidance for working in this repo
└── README.md
```
