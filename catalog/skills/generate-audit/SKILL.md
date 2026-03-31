---
name: generate-audit
description: |
  Use when a repo needs a project-specific audit playbook or local `audit`
  skill. Discovers the repo's stack, gates, docs, interfaces, and risk
  surfaces, then generates a concise audit procedure tailored to that repo.
---

# Generate Audit

Use this skill to create a repo-specific audit plan, or to draft a local
`audit` skill for the current project.

This is a meta-skill. It does not run the full audit by default. It generates
the audit procedure that a repo should use.

## Output Modes

Choose one of these outputs based on the user's request:

- audit plan: a markdown checklist or procedure for a one-off audit
- draft skill: a repo-local `audit` skill ready for refinement
- both: first the audit plan, then a draft skill built from the same findings

## Discovery Workflow

1. Identify the project shape:
   - primary languages and frameworks
   - package/workspace layout
   - build, test, lint, and typecheck commands
   - CI scripts, Make targets, or task runners
2. Identify the project's source-of-truth docs:
   - README
   - contributor instructions
   - architecture or product docs
   - API, protocol, schema, or migration docs
3. Identify interface and drift surfaces:
   - API schemas
   - protocol types
   - generated code
   - config and env var contracts
   - CLI commands and flags
4. Identify workflow surfaces:
   - issue tracker or task system
   - branch and merge conventions
   - release or closeout scripts
   - memory or knowledge files if the repo uses them
5. Identify risk-heavy areas:
   - auth and permissions
   - routers and input validation
   - persistence and migrations
   - external network calls
   - background jobs
   - secrets and token handling

## Audit Modules

Include only the modules that fit the discovered repo. The usual set is:

- build health
- code quality sampling
- contract or schema consistency
- docs truthfulness
- issue hygiene
- foundation review
- security review
- usability and ergonomics
- regression sampling
- session or process retrospective

Omit modules that do not match the repo. Do not invent a frontend UX section
for a backend-only service, or a migration section for a repo with no database.

## Generation Rules

- Generate from discovered facts, not assumptions.
- Prefer the repo's actual commands and paths over generic examples.
- Keep the generated audit concise enough to be used repeatedly.
- Separate generic audit structure from repo-specific bindings.
- Mark expensive or optional phases clearly.
- Default to observation only. Put follow-up actions in a separate section.

When drafting a repo-local `audit` skill, structure it as:

1. purpose and scope
2. audit phases
3. output format
4. optional post-audit actions

## Guardrails

- Do not hardcode Rust, Go, TypeScript, Beads, GitHub, or any specific tool
  unless the repo actually uses it.
- Do not require issue creation, commits, or memory edits by default.
- Do not copy a foreign repo's audit verbatim and swap names.
- Do not let the generated audit become a giant project SOP dump.
- If the repo lacks enough structure to justify a full audit skill, produce a
  lightweight audit plan instead.

## Recommended Output Shape

The generated plan or skill should usually include:

- an executive summary section
- phase-by-phase checks with concrete commands or files
- a severity model for findings
- a final consolidated action list

For a draft skill, keep the first version lean. It is better to generate a
useful 6-phase audit that matches the repo than a bloated 10-phase audit full
of guesses.
