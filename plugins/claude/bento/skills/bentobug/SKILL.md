---
name: bentobug
description: Use when the user explicitly reports a bug or unwanted behavior in a bento skill, hook, or helper script and asks to capture or file it. Captures a structured bento bug report from a required user note. Independent of telemetry — works with zero telemetry data.
recommended_model: low
---

# Bentobug

## Model Guidance

Recommended model: low.

The skill's load-bearing tasks are validating the user's note, picking the
target skill, and emitting a structured report block. Reach for a higher
model only if the conversation contains many ambiguous candidate skills.

## When To Use

Trigger only when all hold:

1. The user is reporting a problem with bento itself — a bento skill, hook,
   helper script, generated plugin artifact, or build/landing flow.
2. The user has expressed intent to capture, file, save, or report it (e.g.
   `/bentobug`, "file a bento bug", "capture this against bentobug").
3. The user's note is non-empty and substantive — at least one concrete
   sentence about the observed behavior.

## When NOT To Use

Counter-triggers — do not invoke even if "bento" appears:

- The user merely names or runs a bento skill (`launch-work`, `swarm`, etc.)
  without claiming it misbehaved.
- The user is debugging their own project that happens to be installed via
  bento; the bug is in their code, not in bento.
- The user reports a bug in a non-bento tool (Claude Code itself, a third-
  party plugin, an external CLI) that bento merely orchestrates.
- The bug is in a `bugshot` review or a `storystore` artifact — those
  belong to their own report flows when present.
- The note is empty, vague ("it's broken"), or only a pasted error with no
  context. Ask the user for one concrete sentence first; do not capture.

## Inputs

- **Note (required)**: the user's description of the bug. Must be non-empty
  and contain at least one concrete claim about observed vs. expected
  behavior. If missing or vague, ask once for a concrete sentence and stop.
- **Target (inferred or asked)**: the bento skill, hook, or component the
  bug is about.
- **Context (best effort)**: cwd, branch, current worktree, the recent
  command or skill invocation that surfaced the bug.

## Target Resolution

Resolve the target in this order. Stop at the first that succeeds.

1. **Explicit**: the user named a bento skill or component in the note.
2. **Inferred from immediate context**: a single bento skill was invoked,
   ran, or failed in the current turn or the prior turn, and the note's
   subject plainly matches it. Do not infer from telemetry — telemetry may
   be absent, empty, or stale.
3. **Disambiguation**: ask exactly one question, listing at most the four
   most plausible candidates plus "other". Shape:

   > Which bento component is this about? Options: `<a>`, `<b>`, `<c>`,
   > `<d>`, or other (please name it).

   Wait for the answer before capturing. Do not guess past this point.

If the user replies "other" with a name that is not a bento component, stop
and tell them this is not a bento bug.

## Workflow

1. Verify the note is non-empty and substantive. If not, ask once for a
   concrete sentence; do not capture on a vague note.
2. Resolve the target per **Target Resolution**.
3. Assemble a report block with these fields:
   - `note` — the user's verbatim description.
   - `target` — resolved bento component, or `unknown` only if the user
     answered "other".
   - `cwd`, `branch`, `worktree` — from the current shell when available.
   - `context` — one short paragraph naming the recent bento command,
     skill, or artifact that surfaced the bug, when known.
4. Emit the report block in chat as a fenced markdown section so the user
   can confirm it before any persistence step ships.
5. Tell the user persistence ships in a follow-up (the report writer); for
   now the captured block is the artifact.

## Telemetry Independence

- Do not require, read, or wait on the telemetry store.
- Do not infer the target from telemetry events.
- Do not block capture if telemetry is missing, disabled, empty, or
  corrupt.
- Telemetry may enrich reports in a later, separate flow; this skill must
  remain valid with zero telemetry data.

## Stop Conditions

Stop and ask the user if:

- The note is empty or vague after one prompt for a concrete sentence.
- The target cannot be resolved after one disambiguation question.
- The reported component is not part of bento.

## Non-Negotiable Rules

- Never capture a report with an empty note.
- Never ask more than one disambiguation question per invocation.
- Never invent a target the user did not confirm.
- Never depend on telemetry to function.
