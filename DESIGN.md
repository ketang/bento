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
| Issue tracking | GitHub Issues | Matches the repository host and the included tracker workflow skills |
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
- then runs the repository's `unittest` suite as required verification

Do not hand-edit generated plugin directories or the generated marketplace
manifest.

## Skill implementation pattern

Canonical skills should keep the reusable capability contract in `SKILL.md` and
move only the brittle, repeatable parts of execution into companion files under
the same skill directory.

Use scripts or tools when the logic is:
- stateful or high-cost if misclassified
- better expressed as structured JSON than prose
- dependent on repo facts, git state, or repeatable validation steps
- likely to be reused across runs without reinterpretation

Keep prose in `SKILL.md` when the work is:
- qualitative or judgment-heavy
- dependent on user preferences or external tradeoffs
- better expressed as policy, framing, or workflow guidance

This split keeps canonical capabilities portable while improving runtime
reliability for the parts that benefit from determinism.

## Model Guidance Convention

Each canonical `SKILL.md` may include a short `recommended_model` scalar in
frontmatter with one of `low`, `mid`, or `high`.

This is a Bento-local convention for skill discovery and runtime guidance. It
is not intended as an external standard and should be treated as advisory model
selection metadata.

Each skill should also include a brief `## Model Guidance` section near the top
of the body so the recommendation is visible when the skill content is opened.

Longer rationale should stay in source-side repo documentation rather than in
skill directories when that rationale should not be copied into generated
plugins.

Current rationale summary:

| Skill | Recommended model | Rationale summary |
|---|---|---|
| `beads-issue-flow` | low | Narrow procedural tracker workflow with explicit commands |
| `build-vs-buy` | high | Constraint discovery, external comparison, and tradeoff judgment |
| `closure` | high | Cleanup can discard useful git state despite helper support |
| `generate-audit` | high | Broad repo inference and tailored audit generation |
| `github-issue-flow` | low | Narrow procedural issue workflow with explicit commands |
| `go-pgx-goose` | mid | Stack-specific implementation with migration and fixture risk |
| `graphql-gqlgen-gql-tada` | mid | Schema and generated-artifact workflow with cross-layer effects |
| `land-work` | high | High-cost landing and lease validation workflow |
| `launch-work` | mid | Tracker, branch, and worktree setup with moderate coordination risk |
| `project-memory` | low | Mostly bounded classification and maintenance work |
| `react-vite-mantine` | mid | Repo discovery plus frontend behavior and test judgment |
| `swarm` | high | Parallel triage, overlap prediction, and coordinated landing |

## Hook format

Scripts in `hooks/<event-name>/<concern>.sh`. Wire into `settings.json` with the tool matcher format. Multiple hooks for the same event are listed as an array within the matcher entry.
