---
name: graphql-gqlgen-gql-tada
description: |
  Use when working in projects that pair gqlgen on the backend with gql.tada on
  the frontend. Covers schema-first backend updates, typed frontend queries, and
  schema sync requirements.
---

# GraphQL Stack

Use this skill when the project uses `gqlgen` for backend GraphQL and
`gql.tada` for frontend typed queries.

## Backend Workflow

1. Edit the schema files.
2. Run the project's code generation step.
3. Implement the generated resolver stubs.
4. Wire any new resolver dependencies through the resolver root.

Do not hand-edit generated files.

## Frontend Workflow

- Use `graphql()` from `gql.tada` for every query and mutation
- Do not use raw string queries that bypass schema validation
- Use generated query types instead of ad hoc manual result typing

## Schema Sync

When the backend schema changes, run the project's frontend schema sync step and
commit the generated frontend schema artifacts.
