---
name: go-pgx-goose
description: |
  Use when working in Go projects that use pgx and Goose migrations. Applies Go
  coding conventions, pgx query patterns, migration workflow, and required build
  and test verification.
---

# Go + pgx + Goose

Use this skill when the project uses Go with PostgreSQL, `pgx`, and Goose
migrations.

## Code Conventions

- Wrap errors with context using `%w`
- Use structured logging, not `fmt.Println`
- Put `context.Context` first
- Prefer behavior-named interfaces defined where consumed
- Pass dependencies explicitly; avoid `init()` globals
- Always parameterize SQL

## Database Conventions

- Use `pgx`/`pgxpool` directly for queries
- Never build SQL with string interpolation
- Write Goose migrations with explicit `Up` and `Down` sections
- If a migration changes fixture-backed tables, update the fixtures too

## Verification

Before marking the task done, run the project's required Go quality gates. The
typical baseline is:

```bash
go build ./...
go vet ./...
go test ./...
golangci-lint run
```

Run database integration tests against a real database when the change touches
database behavior.
