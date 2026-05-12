---
name: issue-completeness-precheck
description: Hard trigger before creating, filing, drafting, or submitting any new tracker issue. Use for Beads, GitHub Issues, Jira, Linear, or other issue trackers to verify that the issue title and body are complete enough for a fresh agent to start work without hidden session context.
recommended_model: low
---

# Issue Completeness Precheck

## Model Guidance

Recommended model: low.

Use a higher-capability model only when the issue describes broad product
behavior, subtle reproduction evidence, security-sensitive work, or a change
whose boundaries are unclear.

## Core Rule

Before an issue enters any tracker, verify that the title and body are
workable from a fresh context. Filing-time agents hold the symptom, the
investigation trail, and the conversation that produced the draft. Later
agents see only the issue body. This structural gap is why issue drafts need
an explicit precheck before filing.

Do not file a normal issue until this skill returns `ready: yes`. If the issue
is only suitable for triage, file it only with the repo's documented triage
marker and copy the unresolved questions into the issue body.

## Fresh Reviewer Requirement

Use a fresh reviewer context whenever the runtime permits it and delegation is
authorized. The reviewer must not receive the originating conversation, the
repro session, investigation notes, diagnosis, unstated assumptions, or files
read while drafting. The reviewer may read only the draft file and write only
the review file.

Do not silently downgrade to self-review when a fresh reviewer can be used.

### Claude Code

Dispatch a Task/subagent with a self-contained prompt. Pass only:

- the draft issue file path
- the review output file path
- optionally, the tracker type or repo name if the draft itself includes
  tracker-specific markers

Instruct the reviewer not to inspect the repo, current chat, shell history, or
any file other than the draft.

### Codex

If the user explicitly allowed subagents or delegation in the current request,
spawn a fresh reviewer agent. Pass only the draft issue file path and review
output file path. Do not fork the current context unless that is the only
available mechanism and the reviewer prompt still forbids using prior context.

If delegation is unavailable or not authorized, run the same verdict template
locally while reading only the draft file and mark the verdict as
`review_mode: local-fallback`.

Do not use local fallback for broad, high-risk, ambiguous, or subtle repro
issues. Ask for permission to launch a fresh reviewer instead.

## Workflow

1. Write the proposed issue title and body to a temp file. Reserve a sibling
   path for the verdict:

   ```bash
   draft=$(mktemp -t issue-draft.XXXXXX.md)
   review=${draft%.md}.review.md
   ```

2. Run the fresh reviewer requirement above.

3. Require the reviewer to write this verdict shape:

   ```text
   review_mode: fresh-reviewer|local-fallback
   ready: yes|no|triage-only
   could_start_now: <one or two sentences>
   ambiguities_or_missing_info:
   - ...
   acceptance_checks:
   - ...
   smallest_repro_or_evidence:
   - ...
   in_scope_out_of_scope:
   - ...
   too_broad: yes|no plus reason
   ```

4. Read the verdict.
   - `ready: yes` permits normal filing.
   - `ready: triage-only` permits filing only with the repo's documented
     triage marker and unresolved questions copied into the issue body.
   - `ready: no` means revise the draft and repeat the precheck before filing.

5. Delete the temp files after the issue is submitted or abandoned.

The tracker never receives a normal issue that has not passed this loop.

## Completeness Criteria

The issue body should give a future agent enough information to start without
recovering hidden context:

- observable symptom, desired behavior, or concrete change request
- smallest known reproduction, evidence, or source artifact
- acceptance checks or observable done criteria
- explicit in-scope and out-of-scope boundaries when scope could expand
- rough size signal when the work might exceed one normal task
- unresolved questions, if filing for triage

## Non-Negotiable Rules

- Do not rely on memory of the current session to justify filing.
- Do not pass private draft reasoning to the reviewer unless it is also in the
  issue body.
- Do not file `ready: no` drafts.
- Do not file `ready: triage-only` drafts as normal ready work.
- Do not invent tracker labels, statuses, or project fields; use only the
  repo's documented tracker policy.
