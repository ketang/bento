---
schema_version: 1
title: Cross-Check Gets an Independent Cross-Runtime Review
slug: cross-check-independent-runtime-review
status: active
authority: observed
change_resistance: low
locked_sections:
  - Intent
---

# Cross-Check Gets an Independent Cross-Runtime Review

## Intent
Before an issue draft is filed, a plan is presented, or branch work is considered complete, cross-check hands the artifact to the opposite agent runtime for an independent, read-only critical review, since a cross-model reviewer has different blind spots than self-review.

## Story

An agent finishes work on a branch and is about to consider it complete. Cross-check triggers automatically at this hard-trigger moment. The agent identifies the artifact type — code, issue, or plan — and for code, builds the diff against the base branch (`git merge-base HEAD <primary-branch>`), covering committed, staged, unstaged, and untracked changes, run from the worktree so the reviewer can read surrounding files. It probes for the counterpart runtime with `cross-check-detect.py`, then runs the counterpart read-only via `cross-check-run.py`, which sets `CROSS_CHECK_ACTIVE=1` on the child so a nested cross-check self-skips instead of recursing, and strips identity and credential environment variables before spawning it. The counterpart runs with a strictly read-only toolset — Codex `--sandbox read-only`, Claude `--tools "Read,Grep,Glob" --permission-mode dontAsk` — and must echo back an unguessable per-run identity id plus the artifact's SHA-256 digest; a response missing or mismatching either is rejected as stale or misrouted, never accepted as a valid review. When the cross run fails — nonzero exit, empty output, timeout, or a rejected identity block — cross-check falls back to dispatching an independent same-runtime reviewer instead, and renders that review labeled DEGRADED so the operator knows it wasn't a genuine cross-model check. Either way, cross-check writes the review to `/tmp/cross-check-<slug>-<ts>.md` and presents it inline. The implementing agent assesses findings, fixes valid problems within the authorized scope, runs relevant checks, and records the review path and finding dispositions in the task summary or tracker note. It continues after a clean review or once BLOCKER and MAJOR findings are fixed or dismissed with technical reasoning, without requiring blanket operator acknowledgment. It pauses for unresolved decisions needing operator input, changes beyond the authorized scope, or approvals independently required by the surrounding workflow, including an explicit request to review findings before proceeding. The reviewer remains read-only; the implementing agent may edit to address findings.

## Expected Behavior

- Cross-check fires at three hard-trigger moments: an issue draft ready to file, a plan ready to present, and branch work considered complete.
- The reviewer is always the runtime the caller is not (Claude invokes Codex and vice versa); the direction is automatic, not chosen.
- For a `code` artifact, the diff is computed against `git merge-base HEAD <primary-branch>` and covers committed, staged, unstaged, and untracked changes.
- The counterpart runs strictly read-only (Codex `--sandbox read-only`; Claude restricted to `Read,Grep,Glob` with `--permission-mode dontAsk`) and is never granted write or exec access.
- `CROSS_CHECK_ACTIVE=1` is always set for the child reviewer, and the same marker causes cross-check to self-skip when it is already the reviewer, preventing recursion.
- Identity/credential environment variables are stripped before the counterpart is spawned; only variables the counterpart genuinely needs survive.
- A cross review is accepted only when its identity block echoes back the run's unguessable id and the artifact's SHA-256 digest; a missing or mismatched block is treated as a fallback trigger, never as a successful review.
- On cross-run failure (nonzero exit, empty output, timeout, or rejected identity) or when detection recommends fallback, an independent same-runtime reviewer is dispatched instead and its output is rendered labeled DEGRADED.
- The reviewer stays read-only. The implementing agent evaluates findings rather than accepting them automatically, fixes valid problems within the authorized scope, runs relevant checks, and records the review path and finding dispositions in the task summary or tracker note.
- A clean review or BLOCKER and MAJOR findings fixed or dismissed with technical reasoning allow continuation without blanket operator acknowledgment. Unresolved decisions needing operator input, changes beyond the authorized scope, and approvals independently required by the surrounding workflow still require a pause.
- If both the counterpart and a same-runtime fallback are unavailable, cross-check reports the review was skipped and proceeds without blocking.
- MINOR findings follow the surrounding workflow's existing rules. Issue filing requires existing authorization, and a favorable plan review permits presentation without constituting operator approval of the plan.

## Boundaries

- Review-only: neither the cross-runtime reviewer nor the same-runtime fallback ever edits code, writes patches, or applies fixes.
- Does not run inside another cross-check — the `CROSS_CHECK_ACTIVE` marker causes a self-skip rather than nested recursion.
- Does not treat a missing or mismatched identity/digest echo as an acceptable review, even under time pressure — it is always a fallback trigger.
- Does not proceed with unresolved BLOCKER or MAJOR findings or treat a favorable review as permission to bypass an existing approval.
- Does not require acknowledgment merely because a review completed; its read-only restriction applies to reviewers and does not prevent the implementing agent from addressing findings within the authorized scope.
- Does not trigger for trivial changes where independent review adds nothing.

## Auditable Claims

- The SKILL.md states cross-check is a "Hard trigger" that fires "when an issue draft is ready to file, when a plan is ready to present to the operator, or when work on a branch is complete."
- The SKILL.md states: "The counterpart always runs read-only: Codex `--sandbox read-only`, Claude `--tools \"Read,Grep,Glob\" --permission-mode dontAsk`. Never grant write/exec."
- The SKILL.md states: "A cross review is only accepted when its identity block echoes this run's unguessable id and the artifact's SHA-256. Missing/mismatched identity is a fallback trigger, never a success."
- The SKILL.md states: "Always set `CROSS_CHECK_ACTIVE=1` for the reviewer ... and always honor it as a skip on entry."
- The SKILL.md states: "Label same-runtime fallback output as DEGRADED."
- `cross_check_common.py`'s child-env builder strips identity and credential variables before spawning the counterpart, verified by `test_identity_and_credential_vars_are_stripped` and `test_leaky_caller_env_does_not_reach_counterpart` in `tests/cross_check/test_cross_check.py`.
- Identity validation rejecting missing blocks, wrong ids, and wrong digests is verified by `IdentityValidationTest` in `tests/cross_check/test_cross_check.py` (`test_missing_block_rejected`, `test_wrong_id_rejected`, `test_wrong_digest_rejected`).
- The read-only, no-approval-flag shape of the counterpart commands is verified by `test_codex_command_is_read_only_and_has_no_approval_flag` and `test_claude_command_is_read_only_toolset`.
- The SKILL.md states that cross-check adds no blanket operator-acknowledgment requirement; BLOCKER and MAJOR findings must be fixed or dismissed with technical reasoning before continuing.
- The SKILL.md requires existing authorization for issue filing and states that a favorable review does not constitute operator approval of a plan.

## Evidence

### Tests
- `tests/cross_check/test_cross_check.py`

### Docs
- `catalog/skills/cross-check/SKILL.md`
