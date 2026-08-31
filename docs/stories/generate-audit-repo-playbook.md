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

A team already using bento explicitly asks an agent to "generate an audit plan" for their Go + PostgreSQL service rather than requesting a direct audit report. Because they asked for generated material by name, the deprecated generate-audit entrypoint is the path taken instead of the reusable `audit` skill; an ordinary "audit this project" request would route to `audit` instead. generate-audit owns no assets of its own — it borrows the shared discover helper (`../audit/scripts/audit-discover.py`) and the module list, discovery checklist, and generation rules that live with `audit`. It confirms the user genuinely wants generated material, runs the shared discovery helper and checklist to build the deterministic base layer, and then shapes one of three legacy output modes the user chooses: a markdown audit plan, a draft repo-local audit skill, or both. Any drafted local skill is named repo-specifically — e.g. `project-audit` — never `audit`, since a same-named local skill would shadow `bento:audit`. Once a repo-local skill is generated, it is committed through the repo's normal issue-backed flow and a one-line regeneration rationale is recorded in the repo's agent doc so a future maintainer knows what produced it and when to refresh it.

## Expected Behavior

- The agent first confirms the user explicitly wants generated audit material rather than a direct report from `audit`.
- generate-audit owns no helper or reference assets of its own; discovery, module selection, and generation rules are all borrowed from the `audit` skill.
- Output modes are: audit plan, draft skill, or both — user's choice.
- A generated repo-local skill is named repo-specifically (e.g. `project-audit`), never `audit`, to avoid shadowing `bento:audit`.
- A generated repo-local skill is committed through the repo's issue-backed flow, with a one-line rationale recorded in the repo's agent doc.
- A one-off audit plan (no drafted skill) needs no commit or rationale line.

## Boundaries

- Does not run the full audit itself by default — it generates the procedure or a draft skill.
- Does not handle ordinary "audit this project" requests; those route to the `audit` skill.
- Does not own its own discovery helper, module list, or generation rules; they live with the `audit` skill.
- Does not require issue creation, commits, or memory edits for a one-off audit plan with no drafted skill.

## Auditable Claims

- The SKILL.md describes generate-audit as a "Deprecated compatibility entrypoint" and states: "Do not route ordinary \"audit this project\" requests here."
- The SKILL.md states: "This entrypoint owns no assets of its own." The helper it invokes is `../audit/scripts/audit-discover.py`.
- Output modes are documented as: audit plan, draft skill, both.
- The SKILL.md states: "Name any generated repo-local skill something repo-specific, such as `project-audit`. Do not name it `audit`."
- The SKILL.md's "Committing the Generated Skill" section states a generated repo-local audit skill "is a tracked project artifact, not scratch output" and must be committed with a one-line rationale recorded in the repo's agent doc.

## Evidence
### Tests
- `tests/audit/test_audit_discover.py`
### Docs
- `catalog/skills/generate-audit/SKILL.md`
- `catalog/skills/audit/SKILL.md`
- `catalog/skills/audit/references/generation-rules.md`
