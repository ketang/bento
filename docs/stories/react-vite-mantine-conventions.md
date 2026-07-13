---
schema_version: 1
title: React Vite Mantine Discovers Conventions Before Component Edits
slug: react-vite-mantine-conventions
status: active
authority: observed
change_resistance: low
tests_applicable: false
locked_sections:
  - Intent
---

# React Vite Mantine Discovers Conventions Before Component Edits

## Intent
In React/TypeScript/Vite + Mantine projects, this skill discovers the repo's verification commands, component organization, and theme conventions before making any frontend edits.

## Story
An agent is adding a new settings panel component to a React app. Before writing any JSX, the react-vite-mantine skill fires. It reads `package.json`, the Makefile, CI config, and AGENTS.md to find the actual build, lint, test, and typecheck commands. It identifies where shared UI primitives, feature components, and page-level components live in this repo's specific folder structure. It checks how Mantine theming, CSS variables, and app-level providers are configured, and finds which render helpers or test wrappers the repo expects. With that context, the agent places the new component under the correct path, uses Mantine layout components and the repo's theme tokens rather than hardcoded colors, reuses the existing app shell and provider setup, and follows the repo's export style. Tailwind classes are not introduced unless already present.

## Expected Behavior
- Build, lint, test, and typecheck commands are discovered before any edit.
- Component placement follows the repo's existing folder structure, not a generic pattern.
- Mantine layout components and style props are preferred; no hardcoded hex colors.
- The repo's existing app shell, provider, and theme setup is reused.
- Tailwind is not introduced unless the repo already uses it.
- Repo-local conventions take precedence over the skill's fallback defaults.

## Boundaries
- Applies only when the project uses React, TypeScript, Vite, and Mantine together.
- Baseline commands in the skill are fallbacks — not defaults when repo-local conventions exist.

## Auditable Claims
- The SKILL.md states: "Use repo-local commands and conventions when they exist. Treat the baseline commands in this skill as a fallback, not as the default source of truth."
- The SKILL.md prohibits Tailwind unless the repo already uses it, and prohibits hardcoded hex colors.
- The SKILL.md requires reusing the repo's existing app shell, provider, and theme setup.

## Evidence
### Tests
### Surface
- `skill: react-vite-mantine`
### Docs
- `catalog/skills/react-vite-mantine/SKILL.md`
