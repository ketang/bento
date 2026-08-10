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
A team is onboarding a new agent and wants a repeatable audit procedure for their Go + PostgreSQL service. They ask explicitly for generated audit material rather than a one-off report, so generate-audit — now a deprecated compatibility entrypoint that owns no assets of its own — is the path taken; an ordinary "audit this project" request would route to the reusable `audit` skill instead. The skill first confirms that generated material is really what the user wants, then runs the shared discover helper (`../audit/scripts/audit-discover.py`), which returns a JSON snapshot of the project shape: build and test commands, source-of-truth docs, interface surfaces, disabled tests, risk hotspots, and detected static-analysis tools. The agent works through the shared discovery checklist to fill gaps the helper could not answer, selects audit modules from the `audit` skill's module list (schema drift, query safety, API contract, test health — the secrets scan is never optional), and generates a markdown checklist the team can run manually. Optionally, it also drafts a repo-local audit skill under a repo-specific name such as `project-audit` — never `audit`, which would shadow `bento:audit` — commits it through the repo's normal issue-backed flow, and records a one-line regeneration rationale in the repo's agent doc. The output is tailored to what the repo actually uses, not a generic template.

## Expected Behavior
- The agent first confirms the user explicitly wants generated audit material rather than a direct report from `audit`.
- The discover helper is run next; its JSON forms the deterministic base layer.
- The discovery checklist is used to fill gaps the helper cannot answer locally.
- Audit modules are selected from the `audit` skill's module list to match the repo's actual stack; the secrets scan is never skipped.
- Output modes are: audit plan, draft skill, or both — user's choice.
- A generated repo-local skill is named repo-specifically (e.g. `project-audit`), never `audit`.
- A generated repo-local skill is committed through the repo's issue-backed flow, with a one-line rationale recorded in the repo's agent doc.
- Generated content reflects what the repo uses, not a generic template.

## Boundaries
- Does not run the full audit itself by default — it generates the procedure.
- Does not handle ordinary "audit this project" requests; those route to the `audit` skill.
- Does not own its own helper or reference assets; they live with the `audit` skill.
- Does not skip the discovery phase to produce a generic checklist.

## Auditable Claims
- The SKILL.md describes generate-audit as a "Deprecated compatibility entrypoint" and states "Do not route ordinary 'audit this project' requests here."
- The SKILL.md states: "This entrypoint owns no assets of its own." The helper it invokes is `../audit/scripts/audit-discover.py`.
- `audit/scripts/audit-discover.py` emits JSON covering project shape, build/test/lint commands, risk hotspots, and static-analysis tool detection.
- Output modes are documented as: audit plan, draft skill, both.
- `audit/references/generation-rules.md` governs how output is shaped, including its "Optional Legacy Draft Skill Structure" section.

## Evidence
### Tests
- `tests/audit/test_audit_discover.py`
### Surface
- `skill: generate-audit`
- `skill: audit`
### Docs
- `catalog/skills/generate-audit/SKILL.md`
- `catalog/skills/audit/SKILL.md`
- `catalog/skills/audit/references/generation-rules.md`
