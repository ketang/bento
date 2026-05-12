# Audit Discovery Checklist

After running `generate-audit/scripts/audit-discover.py`, fill in the gaps
the helper cannot infer from file structure. Work through the following
surfaces; skip any that do not apply to the discovered repo.

## Project Shape

Primary languages and frameworks, package/workspace layout, build/test/lint/
typecheck commands, CI scripts, Make targets, task runners.

## Source-of-Truth Docs

README, contributor instructions, architecture or product docs, API/protocol/
schema/migration docs, agent-oriented instructions (`AGENTS.md`, `CLAUDE.md`),
and install/setup/quickstart docs claiming a user can accomplish real work.

Critically review documentation, not just existence: correctness, omissions,
drift, weak assumptions, stale contracts, misleading comments, undocumented
constraints, whether agent-facing docs drive high-quality behavior or merely
restate mechanics, and whether any doc is correct-but-irrelevant, obvious,
redundant, or too shallow to help a contributor, operator, or agent succeed.

## Interface and Drift Surfaces

API schemas, protocol types, generated code, config and env var contracts,
CLI commands and flags.

## Workflow Surfaces

Issue tracker, branch and merge conventions, release or closeout scripts,
memory or knowledge files.

## Automated Test Health

Inspect `test_automation_health.disabled_signals`. Look for disabled,
skipped, quarantined, muted, or bypassed tests in code, CI, task runners, and
docs. Treat these as findings candidates when they reduce confidence or
normalize broken test workflows. Explain what risk each disabled path leaves
untested.

## Demo and Walkthrough Drift

Inspect `demo_walkthrough_signals`. When a repo has a browser demo or
walkthrough, include a warning-level audit surface that checks whether it still
matches current routes, navigation, accessible names, selectors, seed data,
auth/session setup, app/container startup, functional tests, screenshot
artifacts, visible/headless parity, and warning queue handling. Escalate only
when the demo is part of an established required gate.

## Risk-Heavy Areas

Auth and permissions, routers and input validation, persistence and
migrations, external network calls, background jobs, secrets and token
handling.

## Documentation Truthfulness (Command Checks)

Inspect `documentation_analysis.commands` and
`documentation_analysis.command_consistency`. Prioritize install, setup,
quickstart, run, build, and test commands. Execute documented commands when
they are safe, local, and relevant. Treat failing, drifting, or misleading
assumptions as findings.

## Fuzz-Target Candidacy (Go)

For Go repos, inspect `static_analysis.language_signals.Go.fuzz_targets`.
Zero existing `Fuzz*` test functions combined with any of the following
is a recommendation gap:

- Functions with signature `func([]byte) (T, error)` or `func(string, ...) (T, error)`
  in packages classified as risk surfaces (parsers, decoders, transport framing,
  position math, editor codecs).
- Packages named or path-containing: `parser`, `decoder`, `transport`, `codec`,
  `edit`, `lsp`, `format`.

For each candidate, propose a minimal fuzz target and suggest:
`go test -fuzz=FuzzX -fuzztime=30s ./path/to/package`

## Static Analysis Surface

Read `generate-audit/references/static-analysis-tools.md`. Cross-reference
`static_analysis.installed_tools` (tools that will actually run) against
`static_analysis.applicable_tools` (tools that fit the repo but may be
absent from `PATH`), note gaps from `missing_by_language` and
`missing_cross_language`, read each installed tool's config file, and flag
disabled rules, raised thresholds, or excluded paths as findings. Tools in
`applicable_tools` but not `installed_tools` are recommendations, not run
candidates.

## Quality Standards Binding

Read `generate-audit/references/quality-standards.md`. This governs the code
quality audit phase. Sample files in `risk_surfaces` first, then highest-
churn files from
`git log --format='' --name-only | sort | uniq -c | sort -rn | head -20`,
then the remainder.
