---
schema_version: 1
title: Audit Produces a Report-First Quality Review
slug: audit-report-first-quality-review
status: active
authority: observed
change_resistance: low
locked_sections:
  - Intent
---

# Audit Produces a Report-First Quality Review

## Intent
When a project needs a direct software quality audit, the audit skill runs deterministic discovery, inspects the risk surfaces that discovery and the checklist surface, and produces a durable, evidence-backed report rather than a generated procedure or a project-specific skill.

## Story
A maintainer asks an agent to audit their repository for quality and correctness before a release. The agent runs `audit/scripts/audit-discover.py` first, treating its JSON output as a deterministic base layer of project shape, build/test/lint commands, source-of-truth docs, interface surfaces, disabled-test signals, risk hotspots, and detected static-analysis tools. It checks for an optional audit profile under the agent-plugins convention, applying only human decisions and routing preferences from it, never letting stale profile data override freshly discovered facts. It works through the discovery checklist to fill gaps the helper could not answer, then selects only the audit modules that match what was actually discovered — for example, build health and race-detection modules only for a Go repo with concurrency signals, mutation testing only for packages already at or above the coverage gate, and the secrets scan unconditionally because it is never optional. The agent runs safe local verification commands and records exact commands and outcomes, but does not run destructive, environment-mutating, or production-data commands just because docs mention them. It produces a structured, evidence-backed report — findings by severity with file/line evidence, impact, and a concrete recommendation — and does not generate a project-specific audit skill or file tracker issues unless the user explicitly asks for that follow-up.

## Expected Behavior
- The deterministic discovery helper runs first and its JSON output forms the factual base layer for the audit, not the whole audit.
- An optional audit profile, if present, contributes only human decisions and routing preferences; it never overrides freshly discovered facts such as commands, tools, or file inventories.
- Audit modules are selected to match the discovered repo; modules that do not fit the repo shape are omitted (e.g. no frontend UX section for a backend-only service).
- The secrets scan module is always included regardless of repo shape.
- Mutation testing is gated: only applied to packages already at or above the coverage threshold and classified as a risk surface; below-threshold packages get a note that mutation testing is premature.
- Verification commands that are safe and locally available are run and their exact commands and outcomes recorded; destructive, environment-mutating, deploy, release, payment, email, migration, or production-data commands are not run even if referenced in docs.
- The default output is a durable audit report with structured, severity-ranked, evidence-backed findings and a prioritized action list, not a generated procedure or a project-specific audit skill.
- Tracker issues are drafted from accepted findings only if the user asks for that follow-up, and only after the repo's issue-readiness workflow runs.

## Boundaries
- Does not generate a project-specific audit skill or checklist by default — that is the deprecated `generate-audit` entrypoint's job, invoked only when the user explicitly wants generated material.
- Does not create tracker issues unless the user approves that follow-up after reading the report.
- Does not run destructive, environment-mutating, deploy, release, payment, email, migration, or production-data commands, even when repo docs describe them.
- Does not invent audit modules for surfaces the repo does not have (e.g. a migration section for a repo with no database).
- Does not let an audit profile override current tool results or file contents.

## Auditable Claims
- The SKILL.md states: "Do not generate a project-specific audit skill by default, and do not create tracker issues unless the user approves that follow-up after reading the report."
- The SKILL.md states the secrets scan module is "always include" and elsewhere: "Secrets scan is never optional."
- The SKILL.md describes mutation testing as "gated - apply only to packages with line coverage >= 80% AND classified as risk surface; below threshold emit 'mutation testing premature; raise coverage first'".
- The SKILL.md Guardrails state: "Do not let profile data override current tool results or file contents" and "Do not file issues, edit memory, commit, or rewrite project policy as part of the audit unless the user explicitly asks."
- The Workflow section states: "Do not run destructive, environment-mutating, deploy, release, payment, email, migration, or production-data commands just because docs mention them."
- `audit/scripts/audit-discover.py` emits JSON covering project shape, build/test/lint commands, source-of-truth docs, interface surfaces, disabled-test signals, risk hotspots, and static-analysis tool detection, verified by `tests/audit/test_audit_discover.py`.

## Evidence

### Tests
- `tests/audit/test_audit_discover.py`

### Surface

### Docs
- `catalog/skills/audit/SKILL.md`
- `catalog/skills/audit/references/generation-rules.md`
- `catalog/skills/audit/references/control-integrity.md`
