---
schema_version: 1
title: GitHub Issue Lifecycle Management
slug: github-issue-lifecycle
status: active
authority: observed
change_resistance: low
tests_applicable: false
locked_sections:
  - Intent
---

# GitHub Issue Lifecycle Management

## Intent
In repos that use GitHub Issues as their tracker, the github-issue-flow skill governs how agents discover, claim, update, and close issues, requiring a completeness precheck before any new issue is filed.

## Story
An agent is starting work on a repo that uses GitHub Issues. It runs `gh issue list` to find an issue covering the current task, reads the title and description, and if the repo uses a claim mechanism (label, assignee, or project field) applies it before any implementation. During implementation, the issue carries the active-claim signal. After the merge to the primary branch is confirmed, the agent closes the issue with a reference to the landing commit. When the agent needs to file a new issue, it invokes issue-readiness-check first and only calls `gh issue create` after receiving `ready: yes`. If work is abandoned without landing, the active-claim signal is cleared rather than the issue closed.

## Expected Behavior
- The agent inspects the relevant issue before implementation begins.
- The active-claim mechanism is applied before implementation, if the repo uses one.
- Issues already carrying the active-claim signal are treated as unavailable unless the repo documents an override.
- Issue closure happens only after verified landing to the primary branch.
- New issues pass issue-readiness-check before `gh issue create` is run.
- Abandoned work clears the active-claim signal rather than closing the issue.

## Boundaries
- Applies only when the project documents GitHub Issues as the canonical tracker.
- Does not invent a claim mechanism if the repo does not document one.
- Does not close issues based on another skill's handoff without independently verifying landing evidence.

## Auditable Claims
- The SKILL.md states: "Before `gh issue create`, use the `issue-readiness-check` skill."
- The SKILL.md states: "Do not close the issue when branch work is merely complete."
- The `gh` CLI is the documented interface for all GitHub Issues mutations.

## Evidence
### Tests
### Surface
- `skill: github-issue-flow`
- `cli: gh issue`
### Docs
- `catalog/skills/github-issue-flow/SKILL.md`
