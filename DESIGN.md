---
name: bento repo design
description: Design decisions for setting up bento as a plugin marketplace for coding agents
type: project
---

# bento — Design Spec

**Date:** 2026-03-30

## What this is

`bento` is a repository for packaging and distributing reusable capabilities for
coding agents. Its current concrete implementation emits generated plugin
artifacts for Claude Code and OpenAI Codex from the same canonical sources. It
stores:
- **Agent skills** — packaged today as Claude Code plugins and Codex plugins
- **Lifecycle hooks** — platform-peer hook sources packaged into generated
  Claude Code and Codex plugins when that runtime supports the event contract

## Why this approach

Bento keeps runtime protocols separate at packaging boundaries. Shared skill
content stays in `catalog/skills/`, while lifecycle hooks live under
`catalog/hooks/<hook-name>/<platform>/` so Claude Code and Codex can each have
their own `hooks.json` and scripts where their hook contracts differ.

## Key decisions

| Decision | Choice | Rationale |
|---|---|---|
| Repo type | Private marketplace | Allows multiple independent plugins; each can be installed/updated separately |
| Hook management | Platform-peer hook sources under `catalog/hooks/<hook-name>/<platform>/` | Keeps Claude and Codex protocols explicit without making either runtime the default |
| Hook organization | One peer source per runtime, each with its own `hooks.json` and scripts | Supports shared intent while allowing event names, output shapes, and command wiring to differ |
| Hosting | GitHub public repo | Required for Claude Code's native `source: github` marketplace format |
| Issue tracking | GitHub Issues | Matches the repository host and the included tracker workflow skills |
| Skill source model | Canonical skills in `catalog/skills/`; generated installable plugins in `plugins/` | Supports both broad and narrow install options without maintaining duplicate skill content |
| Initial plugin set | `bento`, `trackers`, `stacks` | Keeps installation overhead low while still allowing narrower opt-in installs |

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
- `.claude-plugin/plugin.json` — Claude metadata (name, description, version, author)
- `.codex-plugin/plugin.json` — Codex metadata and interface presentation fields
- `assets/` — generated Codex-facing icon, logo, and screenshot assets
- `skills/<skill-name>/SKILL.md` — composed from the canonical shared skill
  contract and any target-platform overlay
- `hooks/hooks.json` and `hooks/scripts/` — copied from the target platform's
  peer hook source when the plugin declares hooks for that runtime

For Codex, these generated artifacts expose installable skills, apps, MCP
servers, hooks, and UI metadata. They do not currently define custom slash
commands, so Bento skills such as `swarm` and `closure` are invoked by skill
name in prompts rather than as `/swarm` or `/closure`.

The root script `scripts/build-plugins` regenerates:
- the plugin directories under `plugins/`
- each plugin's Claude and Codex manifests
- generated Codex-facing plugin assets
- `.claude-plugin/marketplace.json`
- `.agents/plugins/marketplace.json`
- then runs the repository's `unittest` suite as required verification

Do not hand-edit generated plugin directories or the generated marketplace
manifest.

## Cross-Agent Worktree Policy

When a Bento skill creates a linked worktree and the project does not define a
different root, the default location is:

```text
~/.local/share/worktrees/<repo>/<branch>
```

This policy is shared across agent runtimes. It keeps linked worktrees:

- persistent across reboots
- outside `/tmp`, which is reserved for disposable scratch data
- outside the top level of the user's home directory or the project parent,
  which avoids noisy ad hoc checkouts
- outside the checked-out repository, which avoids nested working-copy clutter

Repo-specific docs may override this root when they have a stronger local
convention, but runtime-specific skills should not invent different defaults.
Those overrides should still use a dedicated, durable, user-scoped worktree
root rather than an arbitrary nearby directory.

## Agent-Plugins Convention

Bento ratifies the `agent-plugins` convention as the location and lookup rule
for user-editable plugin customization files.

Rationale: plugins frequently expose user-editable artifacts (prompt templates,
rule lists, allow/deny lists, fill-in-the-blank content skeletons). Without a
shared convention, each plugin chooses its own location ad hoc, and a user who
installs plugins from multiple marketplaces has to learn an inconsistent
scatter of customization paths. A small, focused convention solves layout and
lookup without reaching into orthogonal concerns like cache, runtime state,
install mechanics, or packaging.

Key positions:

- Home-scope base directory honors XDG: `$XDG_CONFIG_HOME/agent-plugins/`,
  falling back to `~/.config/agent-plugins/` when unset.
- Repo-scope base directory is `<repo-root>/.agent-plugins/`.
- Path layout below each base is two-level: `<marketplace>/<plugin>/...`.
  Each plugin chooses its own internal substructure.
- File-level override precedence: repo scope beats home scope beats
  plugin-bundled default.
- Creation mechanics are deliberately unspecified. Plugins may use installers,
  session-lifecycle hooks, first-use self-healing, or manual user setup.

The convention is cross-marketplace and agent-neutral by design; bento is its
first concrete adopter but the intent is that other marketplaces can follow it
without modification. See
[docs/specs/2026-04-24-agent-plugins-convention-design.md](docs/specs/2026-04-24-agent-plugins-convention-design.md)
for the full specification.

## Skill implementation pattern

Canonical skills should keep the reusable capability contract in `SKILL.md`.
When a skill needs runtime-specific instructions, keep those requirements in an
optional platform overlay under the same skill directory:

- `CLAUDE.md` for Claude-specific requirements
- `CODEX.md` for Codex-specific requirements

Generated skill payloads compose `SKILL.md` plus the overlay for the target
platform. Overlay files are not copied as separate files into generated
plugins.

Move only the brittle, repeatable parts of execution into companion files under
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
