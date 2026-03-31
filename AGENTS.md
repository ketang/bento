# AGENTS

## Purpose

This repository is a plugin marketplace for coding agents.

Its job is to store reusable agent capabilities in canonical form and generate
installable plugin bundles from them.

## How to think about the repo

- `catalog/skills/` contains the canonical source material
- `plugins/` contains generated installable artifacts
- `.claude-plugin/marketplace.json` contains generated marketplace metadata
- `hooks/` contains related automation scripts, but hook wiring is external

## Rules for agents

- Treat `catalog/skills/` as the source of truth
- Do not hand-edit generated skill copies under `plugins/`
- Do not hand-edit generated marketplace manifests
- If a skill changes, rebuild generated plugins with `scripts/build-plugins`
- Preserve the separation between platform-agnostic capability content and
  platform-specific packaging

## Framing guidance

Although the current generated output targets Claude Code, the repository
should be documented and maintained as a marketplace for coding agents more
broadly.

When updating docs or structure:

- prefer "coding agents" or "agent plugins" as the primary framing
- mention Claude Code as the current packaging target where relevant
- avoid language that implies the repo is only useful for one agent runtime
  unless that limitation is technically required

## Safe editing guidance

Prefer edits in:

- `catalog/skills/`
- `README.md`
- `DESIGN.md`
- `scripts/build-plugins`
- `hooks/README.md`

Be careful in:

- `plugins/` because contents are generated
- `.claude-plugin/marketplace.json` because it is generated

## Typical maintenance workflow

1. Update canonical skill content in `catalog/skills/`
2. Adjust plugin composition or metadata in the build script if needed
3. Run `scripts/build-plugins`
4. Verify generated plugin output is consistent with the canonical sources
