---
schema_version: 1
title: Bentobug Captures a Structured Bug Report
slug: bentobug-capture-report
status: active
authority: observed
change_resistance: low
tests_applicable: true
locked_sections:
  - Intent
---

# Bentobug Captures a Structured Bug Report

## Intent
When a user reports a concrete misbehavior in a bento skill, hook, or helper script, bentobug gathers the user's note and emits a structured report block.

## Story
A user notices that the launch-work skill created a worktree at the wrong path. They type `/bentobug` and describe what happened. The skill validates that the note is non-empty and contains at least one concrete sentence about observed versus expected behavior, infers that the target component is launch-work, and collects available context — current working directory, branch, recent actions. It emits a structured report block in chat for the user to confirm. Once the user confirms, the skill persists the record by invoking the report writer, `scripts/bentobug-report.py`, which prints the saved record's `id` and `path` as JSON; the skill then reports that path back. It does not open a tracker issue automatically. No telemetry is required; the skill works entirely from the user's note and visible session state, and the writer performs only best-effort telemetry enrichment that is silently skipped on any failure.

## Expected Behavior
- The skill is triggered only when the user explicitly reports a bento bug and provides a substantive note.
- If the note is empty or vague, the skill asks once for a concrete sentence and stops.
- The skill infers the target skill from context or asks the user.
- A structured report block is emitted to chat for the user to confirm.
- After the user confirms, the report is persisted via the report writer (`bentobug-report.py`), which prints the record `id` and `path`.
- The skill does not open a tracker issue automatically; it captures a structured report record.

## Boundaries
- Does not apply to bugs in the user's own project that happen to use bento.
- Does not apply to bugs in non-bento tools bento merely orchestrates.
- Does not apply when the user merely names or runs a skill without claiming it misbehaved.
- Does not require telemetry data — works with zero telemetry.

## Auditable Claims
- The SKILL.md states the note must be "non-empty and contain at least one concrete claim about observed vs. expected behavior."
- The SKILL.md states the skill is "independent of telemetry — works with zero telemetry data."
- The SKILL.md counter-triggers exclude cases where the user merely runs a skill without a bug claim.
- The SKILL.md "Workflow" persists the confirmed report via `scripts/bentobug-report.py`, which "prints the record `id` and `path` as JSON."

## Evidence
### Tests
- `tests/bentobug/test_bentobug_report.py`
### Surface
- `skill: bentobug`
### Docs
- `catalog/skills/bentobug/SKILL.md`
