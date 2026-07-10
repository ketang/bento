---
schema_version: 1
title: Dev Skill Loads and Executes an Unpublished Skill
slug: dev-skill-load-unpublished
status: active
authority: observed
change_resistance: low
tests_applicable: true
locked_sections:
  - Intent
---

# Dev Skill Loads and Executes an Unpublished Skill

## Intent
When a developer needs to test a skill from a local checkout or a specific GitHub commit before it is published to the plugin cache, dev-skill fetches the SKILL.md content and executes it in the current session.

## Story
A developer has added a new `expedition` skill to a local bento clone and wants to verify it behaves correctly before releasing. They invoke dev-skill with the absolute path to the clone and the skill name `expedition`. The skill resolves the SKILL.md by trying the bento canonical layout first (`catalog/skills/expedition/SKILL.md`), then the standard plugin layout. Once found, it loads the content and executes the skill as if it were installed. Alternatively, a reviewer wants to exercise a skill from a specific GitHub commit: they provide a URL with a `@<sha>` ref, and dev-skill fetches the raw content from GitHub and runs it. In both cases, the published plugin cache is not touched.

## Expected Behavior
- The skill accepts an absolute local path or a GitHub URL with an optional `@<ref>` suffix.
- Skill names with path separators or `..` are rejected before any resolution.
- For local sources, the bento canonical layout is tried before the standard plugin layout.
- For GitHub sources, both candidate raw URLs are fetched; the first 200 response wins.
- The loaded skill content is executed in the current session without modifying the plugin cache.

## Boundaries
- Does not install or publish the skill to the plugin cache.
- Does not apply to skills that are already installed and current — those can be invoked directly.
- Applies to any Claude plugin, not just bento.

## Auditable Claims
- The SKILL.md documents the two candidate path patterns for local and GitHub sources.
- Skill names containing `/`, `\`, or `..` trigger a rejection before any fetch.
- GitHub URL parsing extracts `owner`, `repo`, and `ref`, defaulting `ref` to `main` when absent.

## Evidence
### Tests
### Surface
- `skill: dev-skill`
### Docs
- `catalog/skills/dev-skill/SKILL.md`
