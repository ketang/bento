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

## Static Analysis Surface

Read `generate-audit/references/static-analysis-tools.md`. Cross-reference
`static_analysis.detected_tools`, note gaps from `missing_by_language` and
`missing_cross_language`, read each detected tool's config file, and flag
disabled rules, raised thresholds, or excluded paths as findings.

## Quality Standards Binding

Read `generate-audit/references/quality-standards.md`. This governs the code
quality audit phase. Sample files in `risk_surfaces` first, then highest-
churn files from
`git log --format='' --name-only | sort | uniq -c | sort -rn | head -20`,
then the remainder.
