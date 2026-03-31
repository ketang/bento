# bento

Personal Claude Code plugin marketplace — Superpowers skills and hook scripts.

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

## Adding a plugin

Create a subdirectory under `plugins/`:

```
plugins/<plugin-name>/
├── .claude-plugin/
│   └── plugin.json
└── skills/
    └── <skill-name>/
        └── SKILL.md
```

**`plugin.json` format:**
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

**`SKILL.md` format:**
```markdown
---
name: skill-name
description: |
  When Claude should invoke this skill...
---

# Skill content here
```

Then add an entry to `.claude-plugin/marketplace.json` under `plugins`:

```json
{
  "name": "plugin-name",
  "description": "What this plugin does",
  "version": "1.0.0",
  "source": "./plugins/plugin-name",
  "author": {"name": "Ketan Gangatirkar"}
}
```

## Adding a hook

1. Create `hooks/<event-name>/<concern>.sh` (e.g. `hooks/post-tool-use/log.sh`)
2. Make it executable: `chmod +x hooks/post-tool-use/log.sh`
3. Wire it into `~/.claude/settings.json` — see [hooks/README.md](hooks/README.md) for the exact format

## Structure

```
bento/
├── .claude-plugin/
│   └── marketplace.json    # marketplace manifest
├── plugins/                # one subdir per installable skill plugin
├── hooks/                  # hook scripts organized by event type
└── README.md
```
