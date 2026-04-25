# AGENTS

## Purpose

This repository is a plugin marketplace for coding agents.

Its job is to store reusable agent capabilities in canonical form and generate
installable plugin bundles from them.

## How to think about the repo

- `catalog/skills/` contains the canonical source material
- `plugins/` contains generated installable artifacts
- `.claude-plugin/marketplace.json` contains generated Claude marketplace metadata
- `.agents/plugins/marketplace.json` contains generated Codex marketplace metadata
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

## Conventions this repo follows

- `agent-plugins` convention: user-editable plugin customization files live at
  `<repo-root>/.agent-plugins/<marketplace>/<plugin>/...` (repo scope) and
  `$XDG_CONFIG_HOME/agent-plugins/<marketplace>/<plugin>/...` (home scope, with
  the XDG default of `~/.config/agent-plugins/` when unset). Repo scope
  overrides home scope, which overrides the plugin-bundled default. Lookup is
  per file. See
  [docs/specs/2026-04-24-agent-plugins-convention-design.md](docs/specs/2026-04-24-agent-plugins-convention-design.md)
  for the full specification.
  When editing a bento skill that exposes user-editable customization files,
  follow this convention; do not invent ad hoc locations.

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
- `.agents/plugins/marketplace.json` because it is generated

## Version Management

**Every time you modify `catalog/skills/` or `scripts/build-plugins`, evaluate
whether a version bump is warranted before ending the session.**  This includes
any feature branch that touches those paths, even if the change seems small.

Read and follow `.claude/skills/version-bump.md` for the full evaluation
workflow.  In brief:

- **Behavioral changes** → bump required.  Behavioral means: new or changed
  Python logic, new functions, changed control flow, new output fields, new or
  modified SKILL.md workflow steps, new or modified reference docs, new or
  modified test assertions.
- **Cosmetic changes only** → no bump.  Cosmetic means: whitespace, rewording,
  typo fixes, reformatting without semantic change.
- **Mixed** → bump.  When in doubt, bump.

Do not bump manually — `scripts/bump-plugin-versions` handles the version
arithmetic.  After bumping, run `scripts/build-plugins` and commit both together.
Updating `catalog/plugin-versions.json` alone is incomplete: Claude and Codex
see the versions from the generated plugin manifests, so a version increment
must include the regenerated outputs from `scripts/build-plugins`.

Pushes are independent of version bumps. Push eagerly and frequently for safety.

## Typical maintenance workflow

1. Update canonical skill content in `catalog/skills/`
2. Adjust plugin composition or metadata in the build script if needed
3. Run `scripts/build-plugins`
4. Verify generated plugin output is consistent with the canonical sources


<!-- headroom:rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

When running shell commands, **always prefix with `rtk`**. This reduces context
usage by 60-90% with zero behavior change. If rtk has no filter for a command,
it passes through unchanged — so it is always safe to use.

## Key Commands
```bash
# Git (59-80% savings)
rtk git status          rtk git diff            rtk git log

# Files & Search (60-75% savings)
rtk ls <path>           rtk read <file>         rtk grep <pattern>
rtk find <pattern>      rtk diff <file>

# Test (90-99% savings) — shows failures only
rtk pytest tests/       rtk cargo test          rtk test <cmd>

# Build & Lint (80-90% savings) — shows errors only
rtk tsc                 rtk lint                rtk cargo build
rtk prettier --check    rtk mypy                rtk ruff check

# Analysis (70-90% savings)
rtk err <cmd>           rtk log <file>          rtk json <file>
rtk summary <cmd>       rtk deps                rtk env

# GitHub (26-87% savings)
rtk gh pr view <n>      rtk gh run list         rtk gh issue list

# Infrastructure (85% savings)
rtk docker ps           rtk kubectl get         rtk docker logs <c>

# Package managers (70-90% savings)
rtk pip list            rtk pnpm install        rtk npm run <script>
```

## Rules
- In command chains, prefix each segment: `rtk git add . && rtk git commit -m "msg"`
- For debugging, use raw command without rtk prefix
- `rtk proxy <cmd>` runs command without filtering but tracks usage
<!-- /headroom:rtk-instructions -->
