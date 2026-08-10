---
schema_version: 1
title: Issue Readiness Check Validates Before Filing
slug: issue-readiness-check-fresh-review
status: active
authority: observed
change_resistance: medium
tests_applicable: false
locked_sections:
  - Intent
---

# Issue Readiness Check Validates Before Filing

## Intent
Before any new tracker issue is created, issue-readiness-check verifies that the title and body contain enough context for a fresh agent to start work without hidden session knowledge.

## Story
An agent has diagnosed a bug in the land-work skill's worktree cleanup path and wants to file a tracker issue. Before calling `gh issue create` or `bd add`, it invokes issue-readiness-check. The skill uses a fresh reviewer — a subagent that sees only the draft issue file and writes only a review file, without any of the originating conversation, repro session, or investigation notes. The reviewer checks: is the reproduction path self-contained? Are the expected and actual behaviors stated explicitly? Could a fresh agent start work without contacting the reporter? If the review returns `ready: yes`, filing is still gated on the lead-agent recovery loop: every reviewer-flagged ambiguity that is a Lookup — a bounded fact recoverable from the current repo — must be resolved and written into the draft body before the issue is filed, while Decisions are escalated to the user. If it returns `ready: triage-only`, the issue is filed only with the repo's documented triage marker and the unresolved questions copied into the body.

## Expected Behavior
- The precheck fires before any tracker issue is created — hard trigger.
- A fresh reviewer context is used when permitted; self-review is not silently downgraded. The verdict records `review_mode: fresh-reviewer|local-fallback`, and the sanctioned local fallback is never used for broad, high-risk, or ambiguous issues.
- The reviewer receives only the draft file, not the originating conversation or investigation context.
- Issues are filed only after receiving `ready: yes` and resolving every code-recoverable lookup into the draft body.
- `ready: triage-only` allows filing only with the triage marker and unresolved questions in the body.

## Boundaries
- Does not block filing a triage issue — it governs the filing path, not the decision to file.
- Applies to Beads, GitHub Issues, Jira, Linear, or any tracker.
- Does not review existing issues — only pre-filing drafts.

## Auditable Claims
- The SKILL.md states: "Do not file a normal issue until this skill returns `ready: yes`."
- The SKILL.md "Fresh Reviewer Requirement" states: "Do not silently downgrade to self-review when a fresh reviewer can be used."
- The SKILL.md hard-trigger description: "Hard trigger before creating, filing, drafting, or submitting any new tracker issue."
- The SKILL.md lead-agent recovery loop states: "Do not file normal ready work with unresolved code-recoverable lookups."

## Evidence
### Tests
### Surface
- `skill: issue-readiness-check`
### Docs
- `catalog/skills/issue-readiness-check/SKILL.md`
