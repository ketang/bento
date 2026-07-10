---
schema_version: 1
title: Generate Audit Produces a Repo-Specific Audit Playbook
slug: generate-audit-repo-playbook
status: active
authority: observed
change_resistance: low
tests_applicable: true
locked_sections:
  - Intent
---

# Generate Audit Produces a Repo-Specific Audit Playbook

## Intent
When a project needs an audit procedure tailored to its own stack and risk surfaces, generate-audit collects repo facts and shapes them into a markdown checklist, a draft local audit skill, or both.

## Story
A team is onboarding a new agent and wants a repeatable audit procedure for their Go + PostgreSQL service. They invoke generate-audit. The skill runs the discover helper, which returns a JSON snapshot of the project shape: build and test commands, source-of-truth docs, interface surfaces, disabled tests, risk hotspots, and detected static-analysis tools. The agent works through the discovery checklist to fill gaps the helper could not answer, selects audit modules relevant to this stack (schema drift, query safety, API contract, test health), and generates a markdown checklist the team can run manually. Optionally, it also drafts a local `audit` skill that encodes the same procedure for future agents. The output is tailored to what the repo actually uses, not a generic template.

## Expected Behavior
- The discover helper is run first; its JSON forms the deterministic base layer.
- The discovery checklist is used to fill gaps the helper cannot answer locally.
- Audit modules are selected to match the repo's actual stack.
- Output modes are: audit plan, draft skill, or both — user's choice.
- Generated content reflects what the repo uses, not a generic template.

## Boundaries
- Does not run the full audit itself by default — it generates the procedure.
- Does not skip the discovery phase to produce a generic checklist.

## Auditable Claims
- `generate-audit/scripts/audit-discover.py` emits JSON covering project shape, build/test/lint commands, risk hotspots, and static-analysis tool detection.
- Output modes are documented as: audit plan, draft skill, both.
- `generate-audit/references/generation-rules.md` governs how output is shaped.

## Evidence
### Tests
### Surface
- `skill: generate-audit`
### Docs
- `catalog/skills/generate-audit/SKILL.md`
