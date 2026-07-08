---
name: generate-audit
description: Deprecated compatibility entrypoint for legacy requests that explicitly ask to generate a repo-specific audit plan or local audit skill; use `audit` for normal project audits.
---

# Generate Audit

## Compatibility Notice

Use `audit` for direct project audits. `generate-audit` remains only as a
compatibility path for users who explicitly ask to generate a repo-specific
audit plan or a repo-local `audit` skill.

Do not route ordinary "audit this project" requests here. For those, invoke
the reusable `audit` skill, run discovery, inspect applicable risk surfaces,
and produce the audit report directly.

## Legacy Model Guidance

Recommended model: high - legacy generation still requires broad repo
inference and tailored output shaping.

This compatibility entrypoint may produce one of these legacy outputs:

- **audit plan** - a markdown checklist or procedure for a one-off audit
- **draft skill** - a repo-local `audit` skill ready for refinement
- **both** - first the audit plan, then a draft skill from the same findings

## Deterministic Helper

`generate-audit/scripts/audit-discover.py` collects the deterministic base
layer of repo facts before shaping any legacy output.

```bash
generate-audit/scripts/audit-discover.py
```

Use the JSON output as the starting point, then fill gaps using
`generate-audit/references/discovery-checklist.md`.

## Legacy Workflow

1. Confirm the user explicitly wants generated audit material rather than a
   direct report from `audit`.
2. Run the helper; use its JSON as the deterministic base layer.
3. Work through `generate-audit/references/discovery-checklist.md` to fill in
   project shape, docs review, interfaces, workflow surfaces, test health,
   risk areas, documentation truthfulness, static analysis, and quality
   standards. Skip surfaces that do not apply.
4. Select only modules that fit the discovered repo.
5. Generate the requested legacy output, following
   `generate-audit/references/generation-rules.md`.

## Guardrails

- Prefer `audit` unless the user explicitly requested generated audit
  material.
- Generate from discovered facts, not assumptions.
- Keep generated output lean and maintainable.
- Do not require issue creation, commits, or memory edits by default.
- Do not execute destructive or environment-mutating commands just because
  they appear in docs.

For the current direct audit workflow, use `audit/SKILL.md`.
