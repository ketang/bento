---
schema_version: 1
title: Issue Completeness Precheck Validates Before Filing
slug: issue-completeness-precheck-fresh-review
status: active
authority: observed
change_resistance: medium
tests_applicable: true
locked_sections:
  - Intent
---

# Issue Completeness Precheck Validates Before Filing

## Intent
Before any new tracker issue is created, issue-completeness-precheck verifies that the title and body contain enough context for a fresh agent to start work without hidden session knowledge.

## Story
An agent has diagnosed a bug in the land-work skill's worktree cleanup path and wants to file a tracker issue. Before calling `gh issue create` or `bd add`, it invokes issue-completeness-precheck. The skill uses a fresh reviewer — a subagent that sees only the draft issue file and writes only a review file, without any of the originating conversation, repro session, or investigation notes. The reviewer checks: is the reproduction path self-contained? Are the expected and actual behaviors stated explicitly? Could a fresh agent start work without contacting the reporter? If the review returns `ready: yes`, the issue is filed. If it returns `ready: triage-only`, the issue is filed only with the repo's documented triage marker and the unresolved questions copied into the body.

## Expected Behavior
- The precheck fires before any tracker issue is created — hard trigger.
- A fresh reviewer context is used when permitted; self-review is not silently downgraded.
- The reviewer receives only the draft file, not the originating conversation or investigation context.
- Issues are filed only after receiving `ready: yes`.
- `ready: triage-only` allows filing only with the triage marker and unresolved questions in the body.

## Boundaries
- Does not block filing a triage issue — it governs the filing path, not the decision to file.
- Applies to Beads, GitHub Issues, Jira, Linear, or any tracker.
- Does not review existing issues — only pre-filing drafts.

## Auditable Claims
- The SKILL.md states: "Do not file a normal issue until this skill returns `ready: yes`."
- The SKILL.md "Fresh Reviewer Requirement" states: "Do not silently downgrade to self-review when a fresh reviewer can be used."
- The SKILL.md hard-trigger description: "Hard trigger before creating, filing, drafting, or submitting any new tracker issue."

## Evidence
### Tests
### Surface
- `skill: issue-completeness-precheck`
### Docs
- `catalog/skills/issue-completeness-precheck/SKILL.md`
