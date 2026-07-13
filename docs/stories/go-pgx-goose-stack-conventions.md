---
schema_version: 1
title: Go pgx Goose Discovers Stack Conventions Before Editing
slug: go-pgx-goose-stack-conventions
status: active
authority: observed
change_resistance: low
tests_applicable: false
locked_sections:
  - Intent
---

# Go pgx Goose Discovers Stack Conventions Before Editing

## Intent
In Go projects using pgx and Goose migrations, this skill discovers the repo's actual quality gates and migration workflow before applying code or schema changes, so agents follow the project's conventions rather than generic defaults.

## Story
An agent is about to add a new database table to a Go service. Before writing any code or migration, the go-pgx-goose skill fires. It reads the Makefile, CI config, README, and AGENTS.md to find the actual build, test, lint, and integration commands for this repo. It finds how Goose migrations are created and applied here, which DSN or env vars the app uses for Postgres, and whether the repo uses sqlc or checked-in query files alongside pgx. With that context, the agent writes the Goose migration using the repo's naming style, adds parameterized queries using pgx directly (or the repo's existing wrapper), wraps errors with `%w`, and passes context first. It runs the repo's actual test command — not a guessed default — to confirm everything passes.

## Expected Behavior
- Repo-local build, test, lint, and migration commands are discovered before any code is written.
- Goose migrations follow the repo's existing naming, style, and ordering.
- SQL is never built with string interpolation.
- Errors are wrapped with `%w`; `context.Context` is passed first.
- If the repo uses sqlc or checked-in query files, the source SQL is edited and codegen is rerun.
- Repo-local conventions take precedence over the skill's fallback defaults.

## Boundaries
- Does not apply to projects not using pgx and Goose.
- Baseline commands in the skill are fallbacks only — not defaults when repo-local conventions exist.

## Auditable Claims
- The SKILL.md states: "Use repo-local commands and conventions when they exist. Treat the baseline commands in this skill as a fallback, not as the default source of truth."
- The SKILL.md code conventions require `%w` for error wrapping, `context.Context` first, and no `init()` globals.
- The SKILL.md database conventions prohibit SQL string interpolation unconditionally.

## Evidence
### Tests
### Surface
- `skill: go-pgx-goose`
### Docs
- `catalog/skills/go-pgx-goose/SKILL.md`
