---
name: audit-intent-stories
description: |
  Audit fidelity between durable intent story documentation and the software's
  current behavior. Use when Codex needs to compare prose-first user stories
  against tests, commands, source, generated artifacts, and existing docs,
  then report confirmed behavior, drift, missing evidence, stale evidence, and
  undocumented user-facing behavior without rewriting intent to match code.
---

# Audit Intent Stories

Use this skill to report whether a repository's intent stories still match the
software. The skill produces a fidelity report by default. It does not edit
stories unless the user separately asks for updates.

## Defaults

- Look for stories under `docs/stories/` first, then inspect repo docs for a
  documented alternate location.
- Audit accepted and high-authority stories first.
- Treat tests, command output, generated artifacts, source, and docs as
  evidence. Evidence can confirm behavior, but it cannot by itself change
  product intent.
- Prefer precise findings with file paths over broad commentary.

## Story Fields To Audit

- `Intent`: Check for broad contradictions with user-visible behavior, but do
  not over-literalize prose.
- `Boundaries`: Check for current behavior that crosses stated non-goals or
  exclusions.
- `Auditable Claims`: Check each claim against tests, commands, source, docs,
  or generated output.
- `Evidence`: Check whether referenced files, tests, and commands still exist
  and still support the story.
- `Drift Notes`: Carry known unresolved mismatches forward into the report.

## Authority Rules

- `charter`: Report conflicts as high-severity intent drift.
- `contract`: Report conflicts as implementation, test, or documentation drift
  unless explicit human approval changes the story.
- `story`: Report conflicts and recommend whether to clarify story scope,
  update tests, or change implementation.
- `observed`: Report whether the observation still reflects current behavior.
- `draft`: Report gaps and ambiguity, but do not treat conflicts as regressions.

## Finding Categories

Use these categories consistently:

- `confirmed`: the story claim is supported by current evidence.
- `implemented-untested`: code or command behavior appears to support the
  claim, but no relevant test evidence was found.
- `documented-untested`: docs say the behavior exists, but code or tests were
  not found or not inspected deeply enough to verify it.
- `unsupported`: no current evidence supports the claim.
- `contradicted`: current evidence conflicts with the story.
- `stale-evidence`: cited paths, tests, commands, or generated artifacts no
  longer exist or no longer support the claim.
- `implementation-extra`: user-facing behavior exists but no intent story
  covers it.
- `ambiguous-story`: the prose or claim is too vague to audit reliably.
- `intent-conflict`: two or more stories make incompatible user-facing claims.

## Workflow

1. Discover the story set and classify stories by `status` and `authority`.
2. Read the relevant tests, CLI help, public entrypoints, generated artifacts,
   README files, and existing docs that could confirm or contradict each story.
3. For each story, audit `Auditable Claims`, then `Boundaries`, then broad
   `Intent`. Keep evidence scoped to user-visible behavior.
4. Search for likely user-facing behavior not covered by any story. Include it
   as `implementation-extra` rather than silently creating intent.
5. Write a report in chat or to the path the user requested. If no path is
   requested, answer in chat.

## Report Shape

Use this shape for non-trivial audits:

```markdown
# Intent Story Fidelity Report

## Summary

## Confirmed

## Drift And Contradictions

## Missing Or Weak Evidence

## Undocumented Behavior

## Ambiguities

## Recommended Decisions
```

Each finding should include:

- story path and section
- category
- evidence inspected
- concise explanation
- recommended next decision

## Guardrails

- Do not rewrite stories while auditing.
- Do not conclude that a story is stale only because code changed. Explain the
  conflict and identify whether the likely next step is code, tests, docs, or
  product intent.
- Do not require every prose sentence to have a test. Audit concrete claims and
  boundary statements.
- Do not invent missing test coverage goals. Point to specific untested claims
  and risk.
- Do not suppress `implementation-extra` behavior merely because it appears to
  be working. Uncovered user-facing behavior still matters.
