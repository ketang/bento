# dev-skill — Design Spec

**Date:** 2026-04-26

## What this is

`dev-skill` is a bento skill that loads and executes any Claude plugin skill
directly from a local clone or a GitHub repo URL, without touching the
installed plugin cache or modifying the target project. It is designed for
pre-release QA: invoke it in a target project session to test a skill at a
specific source location or commit before publishing.

## Problem

The standard skill invocation path (`Skill` tool) resolves skills from the
installed plugin cache at `~/.claude/plugins/cache/`. Testing unreleased skill
changes with high realism requires either mutating that cache (a global
side-effect that requires restoration) or modifying the target project's
settings. Both approaches add friction and risk.

## Solution

Replicate what the `Skill` tool does — inject skill markdown as active
instructions with a base directory annotation — but source the markdown from
an arbitrary location rather than the installed cache. No mutations anywhere.

## Scope

- **In scope:** loading and executing any skill from any Claude plugin, local
  or remote, at any ref
- **Out of scope:** hook testing (hooks are shell scripts wired via
  `settings.json`; they require a different testing strategy), running
  multiple skills in sequence, automated assertion of skill outcomes

## Architecture

### Placement

`catalog/skills/dev-skill/SKILL.md` — published in the `bento` plugin and
invokable as `bento:dev-skill` from any project session that has bento
installed.

### Inputs

Two inputs are collected at invocation time:

1. **Source** — one of:
   - Local clone path: an absolute or `~`-prefixed filesystem path to a plugin
     checkout (e.g. `~/project/bento`)
   - GitHub URL with optional ref:
     `https://github.com/<owner>/<repo>[@<ref>]`
     where `<ref>` is a commit hash, branch, or tag. Defaults to `main` when
     omitted.

2. **Skill name** — the skill directory name within the plugin (e.g. `swarm`,
   `handoff`).

### Path resolution

**Local source:**

Try candidate paths in order:
1. `<source>/catalog/skills/<name>/SKILL.md` — bento canonical layout
2. `<source>/skills/<name>/SKILL.md` — standard plugin layout

Stop at the first path that resolves. Report clearly if neither exists — the
Read tool surfaces file-not-found naturally.

**GitHub source:**

Parse `<owner>`, `<repo>`, and `<ref>` from the URL. Construct two candidate
raw URLs and attempt to fetch each in order:
1. `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/catalog/skills/<name>/SKILL.md`
2. `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/skills/<name>/SKILL.md`

A 404 response means the candidate does not exist; try the next. Report
clearly if both fail.

### Base directory

The base directory is the directory containing the resolved `SKILL.md`:

- Local: `<source>/catalog/skills/<name>/` or `<source>/skills/<name>/`
- GitHub: `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/catalog/skills/<name>/` (or equivalent)

This replaces the `Base directory:` annotation that the `Skill` tool normally
injects. Announce it explicitly before executing the skill content so script
paths resolve correctly.

### Script detection and warning

Before executing, scan the loaded SKILL.md for references to a `scripts/`
path (simple substring check). If found and the source is a GitHub URL, warn:

> "This skill references helper scripts. Scripts cannot be executed from a
> GitHub source — only the markdown instructions will run. For full-fidelity
> testing, clone the repo locally and point dev-skill at the local path."

Do not block execution; surface the warning and proceed. The user may still
want to exercise the text-only portions of the skill.

### Execution

After resolving the SKILL.md content and announcing the base directory, follow
the loaded skill content as active instructions exactly as if it had been
loaded by the `Skill` tool. The target project's working directory and context
are unchanged — `dev-skill` does not cd, create branches, or modify any file
outside what the loaded skill itself directs.

## Non-negotiable rules

- Do not modify the installed plugin cache.
- Do not modify any file in the target project as part of dev-skill setup.
- Always announce the resolved source path and base directory before executing.
- Always surface the script warning when applicable before executing.
- Do not fabricate a skill path if resolution fails — stop and report.

## Error cases

| Condition | Behavior |
|---|---|
| SKILL.md not found at either candidate path | Stop; report the paths tried |
| GitHub fetch returns non-200 for both candidates | Stop; report the URLs tried and status codes |
| Skill name contains path separators or `..` | Stop; reject as invalid input |
| Source is a GitHub URL but ref is not found | WebFetch 404 surfaces naturally; report it |

## Example invocations

```
# Local bento checkout, testing swarm at HEAD
Source: ~/project/bento
Skill: swarm

# GitHub, specific commit
Source: https://github.com/ketang/bento@a3f9c21
Skill: handoff

# Another plugin, main branch
Source: https://github.com/anthropics/claude-code
Skill: frontend-design
```
