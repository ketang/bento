---
name: generate-intent-stories
description: |
  Create durable, user-perspective intent story documentation for a software
  repository. Use when Codex needs to inspect existing docs, tests, examples,
  commands, and public entrypoints, then draft prose-first stories that
  describe what the software is for without promoting observed behavior to
  accepted product intent.
---

# Generate Intent Stories

Use this skill to create initial intent story documents for a repository.
Intent stories are long-lived, prose-first descriptions of user-facing purpose
and expected experience. They are not backlog tickets and they are not test
fixtures, though they may cite tests and commands as evidence.

## Defaults

- Store stories under `docs/stories/` unless the repository already has a
  documented story location.
- Prefer one story per durable user workflow or user-visible capability.
- Write from the user's or maintainer's perspective, not from the source tree's
  module layout.
- New generated stories must use `status: draft` or `authority: observed`.
  Do not create `accepted`, `contract`, or `charter` stories unless the user
  explicitly supplies that intent.

## Story Format

Use this structure unless the repository already documents a stricter local
format:

```markdown
---
id: stable-short-id
title: Human readable title
status: draft | accepted | deprecated | superseded
authority: charter | contract | story | observed | draft
protected_sections:
  - Intent
  - Boundaries
  - Auditable Claims
last_reviewed: YYYY-MM-DD
---

# Title

## Intent

Stable prose statement of the user-facing outcome the software should provide.

## User Story

Qualitative narrative from the user's or maintainer's perspective.

## Expected Experience

Medium-detail prose about normal usage, visible outcomes, trust assumptions,
and failure modes users should understand.

## Boundaries

What this story does not promise and what agents must not infer from it.

## Auditable Claims

- Concrete user-visible claims that can be checked against docs, tests,
  commands, source, or generated artifacts.

## Evidence

- Tests, commands, docs, or source files that currently support the claims.

## Drift Notes

Known mismatches, weak inferences, ambiguities, or pending human decisions.

## Change Policy

Protected sections require explicit human approval once this story is accepted.
```

## Authority Levels

- `charter`: foundational purpose, non-goals, or product principles. Treat as
  very hard to change.
- `contract`: accepted user-facing behavior. Treat conflicts as implementation
  or test drift unless a human changes intent.
- `story`: intended behavior with lower blast radius or still-evolving details.
- `observed`: behavior inferred from the current repo. Useful, but not
  normative.
- `draft`: proposed story. Freely reviewable and not yet authoritative.

## Workflow

1. Discover existing story docs, README files, product docs, design docs,
   command help, examples, tests, fixtures, public APIs, generated artifacts,
   and top-level scripts.
2. Identify user workflows and user-visible capabilities. Avoid creating one
   story per implementation module unless the module itself is the user-facing
   surface.
3. Draft stories with concise prose and a small `Auditable Claims` section.
   Claims should be concrete enough for a future audit skill to check.
4. Cite evidence for each non-obvious claim. If evidence is weak or inferred,
   say so in `Drift Notes` instead of hiding the uncertainty.
5. Use `authority: draft` for intended behavior inferred from existing docs or
   user conversation. Use `authority: observed` only when the story is primarily
   reverse-engineered from code or tests.
6. Summarize created files, evidence strength, and questions that require human
   product judgment.

## Guardrails

- Do not treat current code behavior as accepted intent by default.
- Do not promote a story to `accepted`, `contract`, or `charter` without
  explicit human direction.
- Do not erase contradictions between docs, tests, and code. Record them as
  drift or open questions.
- Do not make the prose so formal that it becomes an executable spec. Keep the
  main body qualitative; use `Auditable Claims` for checkable statements.
- Do not invent evidence. If no evidence exists, say that plainly.
