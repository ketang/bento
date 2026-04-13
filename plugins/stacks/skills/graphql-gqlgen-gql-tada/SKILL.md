---
name: graphql-gqlgen-gql-tada
description: Use in projects pairing gqlgen (backend) with gql.tada (frontend) — discover schema paths and codegen workflow before applying stack conventions.
recommended_model: mid
---

# GraphQL Stack

## Model Guidance

Recommended model: mid.

Use a higher-capability model when schema changes cascade across multiple
services or generated artifacts with unclear ownership.

Use this skill when the project uses `gqlgen` for backend GraphQL and
`gql.tada` for frontend typed queries.

## Discovery

Before changing schema, resolvers, or frontend queries, identify the repo's
actual GraphQL workflow:

- where backend schema files live and how they are organized
- which command regenerates gqlgen outputs and resolver stubs
- how the repo organizes resolver dependencies and generated files
- which command updates the frontend schema artifacts used by `gql.tada`
- which generated files are committed versus treated as local build outputs
- which build, lint, test, and typecheck commands must pass after GraphQL
  changes

Use repo-local commands and conventions when they exist. Treat the baseline
workflow in this skill as a fallback, not as the default source of truth.

## Backend Workflow

1. Edit the schema files.
2. Run the repo's gqlgen generation step.
3. Implement the generated resolver stubs or schema-driven changes expected by
   the repo.
4. Wire any new resolver dependencies through the repo's existing resolver root
   or dependency injection path.

Do not hand-edit generated files.

## Frontend Workflow

- Use `graphql()` from `gql.tada` for every query and mutation
- Do not use raw string queries that bypass schema validation
- Use generated query types instead of ad hoc manual result typing
- Follow the repo's existing GraphQL document placement and export patterns

## Schema Sync

When the backend schema changes, run the repo's frontend schema sync step and
update the generated frontend schema artifacts that the repo expects to keep in
sync.

## Verification

For behavioral changes with feasible automated coverage, write or update the
relevant backend or frontend test so it fails before implementing the change,
then make it pass.

After GraphQL changes, run the repo's actual build, lint, test, and typecheck
commands for the affected backend and frontend surfaces.

## Guardrails

- Do not assume every repo commits the same gqlgen outputs or frontend schema
  artifacts; check the repo's generated-file policy first.
- Do not hand-edit generated gqlgen files, `gql.tada` artifacts, or synced
  schema outputs.
- Do not add raw query strings or bypass typed GraphQL helpers when the repo
  already uses `gql.tada`.
- Do not change backend schema without updating the frontend sync outputs the
  repo depends on.
- If automated coverage is not feasible, state that explicitly and use the
  closest available verification path.
