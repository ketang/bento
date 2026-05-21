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

The fresh reviewer is a required part of this precheck. Use a fresh reviewer
context whenever the runtime permits it. The reviewer must not receive the
originating conversation, the repro session, investigation notes, diagnosis,
unstated assumptions, or files read while drafting. The reviewer may read only
the draft file and write only the review file.

Do not silently downgrade to self-review when a fresh reviewer can be used. Do
not skip or downgrade the review because the issue seems narrow, obvious,
documentation-only, installability-only, or otherwise low risk. A user not
proactively asking for subagent delegation is not a reason to skip the
reviewer; get any required authorization and run the review.

### Claude Code

Dispatch a Task/subagent with a self-contained prompt. Pass only:

- the draft issue file path
- the review output file path
- optionally, the tracker type or repo name if the draft itself includes
  tracker-specific markers

Instruct the reviewer not to inspect the repo, current chat, shell history, or
any file other than the draft.

### Codex

Subagent review is required when the runtime exposes a subagent/delegation
tool. If the user explicitly allowed subagents or delegation in the current
request, spawn a fresh reviewer agent. Pass only the draft issue file path and
review output file path. Do not fork the current context unless that is the
only available mechanism and the reviewer prompt still forbids using prior
context.

If delegation is available but the current request did not authorize it, ask
for explicit permission before doing anything else with the tracker. Use a
short request such as:

```text
May I launch a fresh subagent to review this issue draft for completeness?
It will receive only the draft path and review output path.
```

If the user grants permission, spawn the fresh reviewer agent. If the user
declines, or delegation is unavailable in the runtime, run the same verdict
template locally while reading only the draft file and mark the verdict as
`review_mode: local-fallback`. Record why a fresh reviewer could not be used.
Do not treat "no subagent delegation was requested" as a valid fallback reason;
the required action is to ask for authorization.

Do not use local fallback for broad, high-risk, ambiguous, or subtle repro
issues. Ask for permission to launch a fresh reviewer instead; if permission
is declined, do not file the issue as normal ready work.

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

4. Read the verdict and handle the `ready` field:
   - `ready: yes` permits normal filing only after the recovery loop below has
     no unresolved code-recoverable lookups.
   - `ready: triage-only` permits filing only with the repo's documented
     triage marker, unresolved questions copied into the issue body, and the
     recovery loop below completed for cheap bounded lookups.
   - `ready: no` means revise the draft and repeat the precheck before filing.

5. Run the lead-agent recovery loop before any filing path when the verdict
   has a non-empty `ambiguities_or_missing_info` list.

   Classify each item as one of:

   - **Lookup**: a current repo fact answerable by reading a bounded set of
     files already named or directly discoverable from the draft. Examples:
     existing symbol names, file paths, function signatures, config values,
     dependency versions, or whether a referenced surface is already wired.
     A lookup does not require choosing behavior, external information, broad
     investigation, or running an environment.
   - **Decision**: a choice that requires judgment, user input, external state,
     product direction, or has no single current answer in the repo.

   Resolve each Lookup before filing. Read the relevant file(s), then edit the
   draft so the answer is available in the issue body itself. Prefer a
   `Current Code Facts` or `Resolved Lookups` section with concrete bullets:
   exact path, symbol or config key, current value, and why the fact matters.
   Include line numbers only when they materially help. Do not file normal
   ready work with unresolved code-recoverable lookups.

   For each Decision, leave the draft unresolved only if the issue is marked
   for triage or if deferring that choice to the implementing agent is an
   explicit and appropriate part of the work. Otherwise ask the user or split
   the issue before filing.

   Keep the recovery loop bounded. If a supposed Lookup cannot be resolved
   from cited or directly relevant files after a focused pass, reclassify it as
   investigation or Decision and handle it through triage, user escalation, or
   issue splitting. The lead must not turn the pre-filing check into the
   implementation task.

   Re-run the fresh reviewer once if lookup resolutions changed scope,
   acceptance checks, reproduction steps, implementation boundaries, or the
   shape of the work. Skip the recheck for mechanical fact insertion only.
   If a second pass still finds blocking gaps, ask the user or file only as
   triage according to the repo's tracker policy.

6. Delete the temp files after the issue is submitted or abandoned.

The tracker never receives a normal issue that has not passed this loop.

## Completeness Criteria

The issue body should give a future agent enough information to start without
recovering hidden context:

- observable symptom, desired behavior, or concrete change request
- smallest known reproduction, evidence, or source artifact
- acceptance checks or observable done criteria
- explicit in-scope and out-of-scope boundaries when scope could expand
- rough size signal when the work might exceed one normal task
- resolved codebase lookups as concrete current facts, not pointers that make
  the future agent repeat the same reconnaissance
- unresolved questions, if filing for triage

## Non-Negotiable Rules

- Do not rely on memory of the current session to justify filing.
- Do not pass private draft reasoning to the reviewer unless it is also in the
  issue body.
- Do not skip the fresh reviewer because the issue looks narrow, low-risk,
  documentation-only, or installability-only.
- Do not use "the user did not request subagent delegation" as a reason to skip
  review; ask for the required authorization instead.
- Do not file `ready: no` drafts.
- Do not file `ready: triage-only` drafts as normal ready work.
- Do not file normal ready work while reviewer-flagged ambiguities still
  include unresolved code-recoverable lookups. "The implementing agent will
  find it" is not an acceptable deferral for bounded facts already present in
  the repo.
- Do not invent tracker labels, statuses, or project fields; use only the
  repo's documented tracker policy.
