# bento

Personal Claude Code plugin marketplace for reusable skills and hook scripts.

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

After registering, plugins in this repo are discoverable and installable via Claude Code's built-in plugin system.

## Plugin model

`bento` keeps canonical skill sources under `catalog/skills/` and generates
installable plugin directories under `plugins/` with `scripts/build-plugins`.

This supports both:

- coarse-grained installs such as `bento-all`
- narrower installs such as `trackers` and `stacks`

Do not hand-edit generated plugin skill directories. Edit the canonical sources
and rebuild the plugins.

## Canonical skill sources

Create or update skills under:

```
catalog/skills/<skill-name>/
└── SKILL.md
```

`SKILL.md` format:

```markdown
---
name: skill-name
description: |
  When Claude should invoke this skill...
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

```
plugins/<plugin-name>/
├── .claude-plugin/
│   └── plugin.json
└── skills/
    └── <skill-name>/
        └── SKILL.md
```

**Generated `plugin.json` format:**
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

## Adding a hook

1. Create `hooks/<event-name>/<concern>.sh` (e.g. `hooks/post-tool-use/log.sh`)
2. Make it executable: `chmod +x hooks/post-tool-use/log.sh`
3. Wire it into `~/.claude/settings.json` — see [hooks/README.md](hooks/README.md) for the exact format

## Structure

```
bento/
├── catalog/               # canonical skill sources
│   └── skills/
├── .claude-plugin/
│   └── marketplace.json    # marketplace manifest
├── plugins/                # generated installable plugins
├── scripts/                # repo utilities such as build-plugins
├── hooks/                  # hook scripts organized by event type
└── README.md
```
