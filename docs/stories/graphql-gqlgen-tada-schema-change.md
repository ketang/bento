---
schema_version: 1
title: GraphQL Stack Discovers Codegen Workflow Before Schema Changes
slug: graphql-gqlgen-tada-schema-change
status: active
authority: observed
change_resistance: low
tests_applicable: true
locked_sections:
  - Intent
---

# GraphQL Stack Discovers Codegen Workflow Before Schema Changes

## Intent
In projects pairing gqlgen (backend) with gql.tada (frontend), this skill discovers the repo's schema paths and codegen workflow before any schema or resolver change, so generated artifacts stay consistent with their sources.

## Story
An agent is adding a new field to a GraphQL type. Before touching any file, the graphql-gqlgen-gql-tada skill fires. It reads the repo to find where backend schema files live, which command regenerates gqlgen outputs and resolver stubs, and which command updates the frontend schema artifacts used by gql.tada. It finds whether generated files are committed or treated as local build outputs. With that context, the agent edits the schema source, runs the repo's gqlgen generation step to update resolver stubs, implements the resolver, then runs the frontend schema update command so gql.tada's typed queries reflect the new field. Build, lint, typecheck, and test commands run last to confirm everything is consistent.

## Expected Behavior
- Schema file locations and codegen commands are discovered before any edit.
- The backend schema is edited first; gqlgen codegen runs before resolver implementation.
- The frontend schema update command is run after the backend is updated.
- Whether generated files are committed is discovered from the repo, not assumed.
- Repo-local commands take precedence over the skill's fallback workflow.

## Boundaries
- Applies only when the project uses gqlgen for backend GraphQL and gql.tada for frontend typed queries.
- Does not apply to projects using other GraphQL generators or client libraries.
- Baseline workflow in the skill is a fallback only.

## Auditable Claims
- The SKILL.md states: "Use repo-local commands and conventions when they exist. Treat the baseline workflow in this skill as a fallback, not as the default source of truth."
- The backend workflow documented in the SKILL.md follows: edit schema → run gqlgen → implement resolvers → update frontend schema artifacts.

## Evidence
### Tests
### Surface
- `skill: graphql-gqlgen-gql-tada`
### Docs
- `catalog/skills/graphql-gqlgen-gql-tada/SKILL.md`
