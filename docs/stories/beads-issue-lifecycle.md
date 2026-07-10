---
schema_version: 1
title: Beads Issue Lifecycle Management
slug: beads-issue-lifecycle
status: active
authority: observed
change_resistance: low
tests_applicable: true
locked_sections:
  - Intent
---

# Beads Issue Lifecycle Management

## Intent
In repos that use Beads as their tracker, the beads-issue-flow skill governs how agents discover, claim, update, and close issues at the correct lifecycle stage.

## Story
A user points an agent at a body of work tracked in Beads. The agent runs `bd` commands to list open issues, reads titles and descriptions to find one covering the current task, and — if found — claims it by updating the status to the repo's documented active-work status. If no existing issue matches, the agent files a new one before starting work. During implementation, the issue status reflects in-progress state. After the merge to the primary branch is confirmed, the agent closes the issue with a reference to the landing commit. If work is abandoned or handed off without landing, the agent clears the active-work status according to repo policy rather than closing the issue.

## Expected Behavior
- The agent scans open issues before filing a new one.
- Issues in the documented active-work status are treated as unavailable unless the repo documents an override.
- Issue closure happens only after verified landing — never when the branch is merely complete.
- Abandoned work resets the issue status rather than closing it.
- Tracker state is not invented beyond what the repo's policy documents.

## Boundaries
- Applies only when the project explicitly documents Beads as its tracker.
- Does not invent claim semantics beyond what the repo defines.
- Does not close issues based on another skill's handoff without independently verifying landing evidence.

## Auditable Claims
- The SKILL.md states: "Do not close the issue when branch work is merely complete."
- The SKILL.md "Closure Evidence Rule" is described as non-negotiable.
- `bd` commands are the documented interface for all Beads mutations.

## Evidence
### Tests
### Surface
- `skill: beads-issue-flow`
- `cli: bd`
### Docs
- `catalog/skills/beads-issue-flow/SKILL.md`
