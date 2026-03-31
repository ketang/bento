---
name: bento repo design
description: Design decisions for setting up bento as a plugin marketplace for coding agents
type: project
---

# bento — Design Spec

**Date:** 2026-03-30

## What this is

`bento` is a repository for packaging and distributing reusable capabilities for
coding agents. Its current concrete implementation is a Claude Code-compatible
plugin marketplace hosted at `ketang/bento` on GitHub. It stores:
- **Agent skills** — packaged today as Claude Code plugins, installable via the plugin system
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
| Skill source model | Canonical skills in `catalog/skills/`; generated installable plugins in `plugins/` | Supports both broad and narrow install options without maintaining duplicate skill content |
| Initial plugin set | `bento-all`, `trackers`, `stacks` | Keeps installation overhead low while still allowing narrower opt-in installs |

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

Canonical skills live under `catalog/skills/<skill-name>/`.

Generated plugins live at `plugins/<name>/` with:
- `.claude-plugin/plugin.json` — metadata (name, description, version, author)
- `skills/<skill-name>/SKILL.md` — copied from the canonical catalog

The root script `scripts/build-plugins` regenerates:
- the plugin directories under `plugins/`
- each plugin's `plugin.json`
- `.claude-plugin/marketplace.json`

Do not hand-edit generated plugin directories or the generated marketplace
manifest.

## Hook format

Scripts in `hooks/<event-name>/<concern>.sh`. Wire into `settings.json` with the tool matcher format. Multiple hooks for the same event are listed as an array within the matcher entry.
