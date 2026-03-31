---
name: bento repo design
description: Design decisions for setting up bento as a personal Claude Code plugin marketplace
type: project
---

# bento — Design Spec

**Date:** 2026-03-30

## What this is

`bento` is a personal Claude Code plugin marketplace hosted at `ketang/bento` on GitHub. It stores:
- **Superpowers skills** — packaged as Claude Code plugins, installable via the plugin system
- **Hook scripts** — shell scripts that run on Claude Code events, stored for manual wiring into `~/.claude/settings.json`

## Why this approach

The Claude Code plugin system has native support for skills (via marketplace registration + `/install-plugin`) but no native support for hooks. Hooks are configured in `settings.json` and point to arbitrary shell scripts. Storing hooks in this repo alongside plugins keeps everything in one place without requiring a fragile setup script to mutate `settings.json`.

## Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Repo type | Private marketplace | Allows multiple independent plugins; each can be installed/updated separately |
| Hook management | Scripts in `hooks/` + manual `settings.json` wiring | Plugin system doesn't support hooks natively; a setup script would be fragile |
| Hook organization | Subdirs per event, one file per concern | Supports multiple hooks per event cleanly; easy to add/remove individual hooks |
| Hosting | GitHub public repo | Required for Claude Code's native `source: github` marketplace format |

## Registration

```json
// ~/.claude/settings.json
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

## Plugin format

Each plugin lives at `plugins/<name>/` with:
- `.claude-plugin/plugin.json` — metadata (name, description, version, author)
- `skills/<skill-name>/SKILL.md` — skill content with YAML frontmatter

Each plugin must also be listed in `.claude-plugin/marketplace.json` under `plugins[]`.

## Hook format

Scripts in `hooks/<event-name>/<concern>.sh`. Wire into `settings.json` with the tool matcher format. Multiple hooks for the same event are listed as an array within the matcher entry.
