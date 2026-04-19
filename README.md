# bento

`bento` is a plugin marketplace for coding agents.

It packages reusable agent capabilities as installable plugins and keeps
related hook scripts in the same repository. The current implementation emits
generated packaging for Claude Code and OpenAI Codex, but the repo is organized
around a broader idea: versioned, composable capabilities for agentic coding
workflows.

## What lives here

- agent skills packaged as reusable capabilities
- generated plugin bundles assembled from canonical skill sources
- hook scripts for agent-tooling events
- marketplace metadata for discovery and installation

## Project tracking

This repository uses GitHub Issues as its issue tracker.

## Repository model

`bento` keeps canonical skill sources under `catalog/skills/` and generates
installable plugin directories under `plugins/` with `scripts/build-plugins`.

This supports both:

- coarse-grained installs such as `bento`
- narrower installs such as `trackers` and `stacks`

The separation is intentional:

- `catalog/` is the source of truth
- `plugins/` is generated build output

Do not hand-edit generated plugin skill directories. Edit the canonical sources
and rebuild the plugins.

## Worktree convention

When Bento skills need a linked worktree and the repository does not override
the location, use this shared cross-agent default:

```text
~/.local/share/worktrees/<repo>/<branch>
```

This root is for durable linked worktrees across agent runtimes. Do not create
linked worktrees under `/tmp`, at the top level of the user's home directory,
inside the checked-out repository, or as siblings directly under the project
folder unless the project explicitly documents a different convention.

When a project overrides this root, it should still point to a dedicated,
durable, user-scoped worktree directory rather than an ad hoc convenient path.

Use `/tmp` only for ephemeral scratch data or continuation state that can be
recomputed after a reboot or context reset.

## Current target platforms

Today, `bento` emits plugins in Claude Code's marketplace format and Codex's
plugin format. Those are packaging targets, not the full identity of the repo.

If you are documenting or extending this project, prefer framing it as a
marketplace for coding agents first, then describe Claude Code and Codex
compatibility as concrete implementations.

For Codex specifically, the generated plugin format installs skills and plugin
metadata. It does not currently register custom slash commands such as
`/swarm` or `/closure`. Invoke those capabilities by skill name in your prompt
instead, for example "use the `swarm` skill" or "run the `closure` skill on
this repo".

## Install and setup

For the end-user install flow, see
[docs/installing-plugins.md](docs/installing-plugins.md).

For a one-line home-scoped Codex install from GitHub, use:

```bash
curl -fsSL https://raw.githubusercontent.com/ketang/bento/main/install/codex-home.sh | bash
```

For a project-scoped Codex install in the current repository, use:

```bash
curl -fsSL https://raw.githubusercontent.com/ketang/bento/main/install/codex-project.sh | bash
```

That guide covers:

- Claude marketplace registration
- plugin selection
- the home-scoped and project-scoped Codex installers
- generated Codex packaging artifacts
- update and removal guidance
- the separate hook wiring path

## Canonical skill sources

Create or update skills under:

```text
catalog/skills/<skill-name>/
└── SKILL.md
```

Skills may also include companion files such as:

```text
catalog/skills/<skill-name>/
├── SKILL.md
├── scripts/
└── references/
```

These companion files are copied into generated plugins along with `SKILL.md`.

Use companion scripts for deterministic subproblems that are too stateful or
fragile to leave as prose. Good script candidates include repo discovery,
preflight validation, lease checks, structured scans, and other logic that
should produce repeatable machine-readable output. Leave qualitative judgment,
tradeoff analysis, and user-facing recommendations in `SKILL.md`.

`SKILL.md` format:

```markdown
---
name: skill-name
description: |
  When the agent should invoke this skill...
recommended_model: low|mid|high
---

# Skill content here
```

`recommended_model` is a repo-local Bento convention, not an external
interoperability standard. Keep it short so discovery layers can surface it
without paying for a large token budget.

Add a short `## Model Guidance` section near the top of the body as well. The
frontmatter field is for tooling and discovery; the body section is for runtime
guidance when the skill is actually opened.

Keep longer rationale in repo documentation rather than in the skill directory
when you do not want it copied into generated plugins.

## Building plugins

Run:

```bash
scripts/bump-plugin-versions
scripts/build-plugins
```

Use `scripts/bump-plugin-versions` when preparing a shipped plugin update. It
diffs the current tree against the most recent commit that changed
`catalog/plugin-versions.json`, bumps only the affected plugin versions, and
ignores generated outputs such as `plugins/` and marketplace manifests.

Then `scripts/build-plugins`:

- materializes generated plugin directories under `plugins/`
- writes each plugin's `.claude-plugin/plugin.json`
- writes each plugin's `.codex-plugin/plugin.json`
- generates Codex-facing assets under each plugin's `assets/`
- rebuilds the root `.claude-plugin/marketplace.json`
- runs the repository test suite with `python3 -m unittest discover -s tests -t .`
- removes generated plugin directories that are no longer part of the current
  plugin set

The generated marketplace metadata currently targets Claude Code and Codex. The
canonical catalog and helper scripts should remain platform-agnostic unless a
packaging-specific constraint requires otherwise.

## Generated plugin format

Each generated plugin lives at `plugins/<plugin-name>/`:

```text
plugins/<plugin-name>/
├── .codex-plugin/
│   └── plugin.json
├── .claude-plugin/
│   └── plugin.json
├── assets/
│   ├── icon.png
│   ├── logo.png
│   └── screenshot-1.png
└── skills/
    └── <skill-name>/
        └── SKILL.md
```

Generated Claude `plugin.json` format:

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

Generated Codex `plugin.json` format includes:

- the same top-level identity fields as the Claude manifest
- `skills: "./skills/"`
- an `interface` block with display text, capabilities, starter prompts, and
  generated asset references

The current Codex plugin manifest shape in this repo does not include a custom
slash-command registry. Skills are the installable unit; slash commands remain
separate Codex UI behavior.

Generated marketplace manifests are automatic; do not edit
`.claude-plugin/marketplace.json` by hand.

Plugin versions live in `catalog/plugin-versions.json`. Treat that file as the
release boundary for plugin artifacts: the bump script compares the current tree
to the last commit that updated those versions and advances only the plugins
whose canonical shipped inputs changed.

If you increment a plugin version, do not stop at `catalog/plugin-versions.json`.
The surfaced Claude and Codex versions come from the generated artifacts, so you
must run `scripts/build-plugins` and commit the regenerated manifests together
with the version file update.

## Hooks

1. Create `hooks/<event-name>/<concern>.sh` such as `hooks/post-tool-use/log.sh`
2. Make it executable with `chmod +x hooks/post-tool-use/log.sh`
3. Wire it into `~/.claude/settings.json`

See [hooks/README.md](hooks/README.md) for the exact format.

## Structure

```text
bento/
├── catalog/        # canonical skill sources
├── .claude-plugin/ # generated Claude marketplace metadata
├── install/        # end-user installer entrypoints and shared installer helper
├── plugins/        # generated installable plugins
├── scripts/        # repo utilities such as build-plugins
├── hooks/          # hook scripts organized by event type
├── AGENTS.md       # agent-facing guidance for working in this repo
└── README.md
```
