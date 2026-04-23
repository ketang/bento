---
name: generate-audit
description: Use when a repo needs a project-specific audit playbook or local `audit` skill tailored to its stack and risk surfaces.
recommended_model: high
---

# Generate Audit

## Model Guidance

Recommended model: high — this is a meta-skill requiring broad repo inference
and tailored output shaping.

Use this skill to create a repo-specific audit plan, or to draft a local
`audit` skill for the current project. This is a meta-skill: it does not run
the full audit by default. It generates the audit procedure that a repo should
use.

## Deterministic Helper

`generate-audit/scripts/audit-discover.py` collects a deterministic base layer
of repo facts (project shape, build/test/lint/typecheck commands, source-of-
truth docs, interface and drift surfaces, workflow surfaces, disabled-test
signals, risk hotspots, static-analysis tool detection, documentation command
consistency) before the model shapes the audit. Invoke by script path so
approvals stay scoped.

```bash
generate-audit/scripts/audit-discover.py
```

Use the JSON output as the starting point, then fill gaps using
`generate-audit/references/discovery-checklist.md`.

## Output Modes

- **audit plan** — a markdown checklist or procedure for a one-off audit
- **draft skill** — a repo-local `audit` skill ready for refinement
- **both** — first the audit plan, then a draft skill from the same findings

## Workflow

1. Run the helper; use its JSON as the deterministic base layer.
2. Work through `generate-audit/references/discovery-checklist.md` to fill in
   project shape, docs review, interfaces, workflow surfaces, test health,
   risk areas, documentation truthfulness, static analysis, and quality
   standards — skip surfaces that do not apply.
3. Select audit modules from the list below.
4. Generate the output in the requested mode, following
   `generate-audit/references/generation-rules.md`.

## Audit Modules

Include only modules that fit the discovered repo:

- build health
- static analysis (run detected tools; emit run blocks per `static-analysis-tools.md`)
- code quality (model-based review using thresholds and smell catalog from `quality-standards.md`)
- dependency health (outdated packages, unused dependencies, license compliance)
- **secrets scan** (always include; scans git history and working tree)
- contract or schema consistency
- duplication (cross-file clone detection)
- test coverage (gap analysis against risk surfaces; no blanket % target)
- documentation coverage (exported/public symbol coverage)
- docs truthfulness
- documentation utility
- issue hygiene
- foundation review
- security review
- usability and ergonomics
- regression sampling
- session or process retrospective

Omit modules that do not match the repo. Do not invent a frontend UX section
for a backend-only service, or a migration section for a repo with no
database. **Secrets scan is never optional.**

## Output Shape

The generated plan or skill should include: executive summary, phase-by-phase
checks with concrete commands or files, severity model for findings, concrete
remediation guidance tied to findings, and a final consolidated action list.
For a draft skill, keep the first version lean — a useful 6-phase audit that
matches the repo beats a bloated 10-phase audit full of guesses.

See `generate-audit/references/generation-rules.md` for grounding, static-
analysis output format, code-quality sampling, coverage handling,
documentation-finding rules, guardrails, and the draft-skill structure.
