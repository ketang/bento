---
schema_version: 1
title: Compress Docs Reduces Session-Start Token Footprint
slug: compress-docs-token-reduction
status: active
authority: observed
change_resistance: low
tests_applicable: false
locked_sections:
  - Intent
---

# Compress Docs Reduces Session-Start Token Footprint

## Intent
When agent instruction files have grown bloated with duplication and verbose prose, compress-docs produces a reviewable compression plan that removes load-bearing content only after the user explicitly approves each tier.

## Story
A CLAUDE.md file has grown to 800 lines over months. Several sections duplicate content from referenced files, some `@include` paths no longer exist, and three subsections restate the same rule. The user invokes compress-docs. The skill runs the discover helper to build a scope inventory — every in-scope file with byte count and estimated token load, dead references, duplicate passages. It then drafts a compression plan to `docs/specs/YYYY-MM-DD-compress-docs-plan.md` organized by tier. The user reviews the plan, checks the tiers they approve, and the skill applies the reductions tier by tier with a pre-flight drift check and optional backups. After each tier, the user sees what changed. No load-bearing rule is silently removed.

## Expected Behavior
- The discover helper is run first and its output forms the deterministic base layer.
- A compression plan is written to `docs/specs/` for review before any edits.
- The user must tick tier checkboxes before each tier is applied.
- Dead references and duplicate passages are identified explicitly.
- The scope is limited to session-start context files, not general docs or ADRs.

## Boundaries
- Does not apply to general documentation in `docs/` — only to session-start context files.
- Does not apply edits without user approval of each tier.
- Historical design docs, ADRs, and changelogs are explicitly out of scope.

## Auditable Claims
- `compress-docs/scripts/compress-discover.py` emits JSON with scope, dead references, and token estimates.
- The compression plan is written to `docs/specs/` before any edits are applied.
- The SKILL.md documents a "preserved-claims guardrail" — no load-bearing content is silently removed.

## Evidence
### Tests
### Surface
- `skill: compress-docs`
### Docs
- `catalog/skills/compress-docs/SKILL.md`
