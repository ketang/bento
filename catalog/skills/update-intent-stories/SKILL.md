---
name: update-intent-stories
description: |
  Safely maintain existing intent story documentation after software changes.
  Use when Codex needs to refresh evidence, review metadata, drift notes, or
  wording while preserving protected intent, boundaries, and accepted claims;
  requires explicit human approval before changing high-authority story
  meaning to match changed code.
---

# Update Intent Stories

Use this skill to maintain existing intent stories without laundering software
drift into product intent. The default posture is conservative: update
evidence and review metadata freely when supported, but do not change accepted
intent, boundaries, or protected claims without explicit human approval.

## Defaults

- Look for stories under `docs/stories/` first, then inspect repo docs for a
  documented alternate location.
- Preserve story `id` values.
- Preserve protected sections for `accepted` stories unless the user explicitly
  approves an intent change.
- Prefer adding `Drift Notes` over rewriting a story to hide a mismatch.

## Edit Classes

Classify proposed edits before applying them:

- `evidence-refresh`: update cited tests, commands, paths, generated artifacts,
  or supporting docs. Allowed by default.
- `review-metadata`: update `last_reviewed` or similar metadata after actual
  review. Allowed by default.
- `drift-note`: record a mismatch, weak inference, stale citation, or pending
  decision. Allowed by default.
- `prose-clarification`: improve wording without changing meaning. Allowed only
  when the preserved meaning is obvious.
- `claim-change`: add, remove, or materially change an `Auditable Claims` item.
  Requires explicit approval for accepted stories.
- `boundary-change`: add, remove, narrow, or broaden a `Boundaries` statement.
  Requires explicit approval for accepted stories.
- `intent-change`: change the user-facing purpose, promise, or non-goal of the
  story. Requires explicit approval for accepted stories.
- `authority-change`: change `status`, `authority`, or protected sections.
  Requires explicit approval.

## Authority Rules

- `charter`: Do not change protected meaning unless the user explicitly asks to
  revise the charter-level intent.
- `contract`: Treat conflicts with code or tests as drift to report, not as a
  reason to rewrite the story.
- `story`: Clarify cautiously; ask before changing meaning.
- `observed`: May be updated to match current evidence, but do not promote to
  accepted intent without approval.
- `draft`: May be edited freely, but keep evidence and uncertainty visible.

## Workflow

1. Discover existing stories and any local story-format guidance.
2. Read the story before editing it. Identify `status`, `authority`, and
   protected sections.
3. Inspect relevant evidence: tests, commands, source, docs, generated
   artifacts, and recent diffs if available.
4. Classify each proposed edit with the edit classes above.
5. Apply allowed edits. For edits that require approval, stop and present the
   proposed change with the reason approval is required.
6. When code or tests conflict with an accepted story, add or update a
   `Drift Notes` entry and present the human decision needed.
7. Summarize changed files, blocked edits, and remaining drift.

## Drift Decision Prompt

When implementation and accepted intent conflict, use this shape:

```markdown
Story: docs/stories/<story>.md
Conflict: Current evidence shows <current behavior>, but the accepted story says <intent>.

Decision needed:
1. Treat implementation as wrong and fix code or tests.
2. Treat the story as outdated and explicitly revise intent.
3. Split current behavior into an `observed` story and keep accepted intent unchanged.
4. Deprecate or supersede the story.
```

Do not choose one of these on the user's behalf unless the user already gave
clear direction.

## Guardrails

- Do not update accepted protected sections just because code changed.
- Do not delete contradicted stories to make an audit look clean.
- Do not promote `observed` or `draft` behavior to accepted intent without
  explicit approval.
- Do not remove boundaries because implementation crossed them. Record drift.
- Do not silently widen claims. Add new claims only when they are intentional
  or explicitly marked as draft or observed.
- Do not stage, commit, or push unless the user explicitly asks for that as
  part of the surrounding repository workflow.
