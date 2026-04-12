---
name: go-pgx-goose
description: Use in Go projects using pgx and Goose migrations — discover repo quality gates and migration/codegen commands before applying stack conventions.
recommended_model: mid
---

# Go + pgx + Goose

## Model Guidance

Recommended model: mid.

Use a higher-capability model when schema changes, fixture coupling, or
database integration risk make the task hard to bound safely.

Use this skill when the project uses Go with PostgreSQL, `pgx`, and Goose
migrations.

## Discovery

Before changing code or migrations, identify the repo's actual workflow:

- build, test, lint, and integration commands from `Makefile`, task runners,
  CI, `README`, and `AGENTS.md`
- how Goose migrations are created, applied, and rolled back in this repo
- which DSN or env vars the app and tests use for Postgres
- whether the repo uses `sqlc`, checked-in query files, fixture loaders, or
  seed scripts alongside `pgx`

Use repo-local commands and conventions when they exist. Treat the baseline
commands in this skill as a fallback, not as the default source of truth.

## Code Conventions

- Wrap errors with context using `%w`
- Use structured logging, not `fmt.Println`
- Put `context.Context` first
- Prefer behavior-named interfaces defined where consumed
- Pass dependencies explicitly; avoid `init()` globals
- Always parameterize SQL
- If the repo uses checked-in query files or SQL/code generation, edit the
  source SQL and rerun the repo's codegen step instead of patching generated Go

## Database Conventions

- Use `pgx`/`pgxpool` directly for queries unless the repo already standardizes
  on a local wrapper or repository layer
- Never build SQL with string interpolation
- Follow the repo's existing Goose migration style, naming, and ordering
- When the repo uses SQL Goose migrations, keep explicit `Up` and `Down`
  sections
- Reuse the repo's existing DSN and bootstrap pattern for migration and test DB
  access
- If a migration changes fixture-backed tables, update the fixtures too
- If schema changes affect seed or bootstrap data, update those paths in the
  same pass

## Verification

Before marking the task done, run the project's required Go quality gates. Use
the repo's actual command surface first. The typical fallback baseline is:

```bash
go build ./...
go vet ./...
go test ./...
golangci-lint run
```

Run migration verification or database integration tests against a real database
when the change touches schema, queries, fixtures, or database behavior.

## Guardrails

- Do not invent new Postgres env var or DSN names when the repo already has a
  convention.
- Do not hand-edit generated code from `sqlc` or similar tools.
- Do not assume every repo exposes `golangci-lint` or raw `goose` commands
  directly; check the repo's wrappers first.
- Do not land schema changes without matching fixture, seed, or test updates
  when the repo depends on them.
