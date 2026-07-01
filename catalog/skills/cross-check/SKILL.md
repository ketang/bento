---
name: cross-check
description: Hard trigger — invoke when an issue draft is ready to file, when a plan is ready to present to the operator, or when work on a branch is complete. Hands the artifact to the opposite agent runtime (Claude↔Codex) for an independent, read-only critical review; falls back to an independent same-runtime reviewer when the counterpart is unavailable. Review-only; soft gate.
---

# Cross-check

Get an independent critical review of your work from the *other* agent runtime
before it advances. A cross-model reviewer has different training and different
blind spots, so it catches what self-review misses.

## When to use (hard trigger)

Invoke at any of these three moments:

- an **issue draft** is ready to file,
- a **plan** is ready to present to the operator,
- **work on a branch** is considered complete.

Direction is automatic: the reviewer is always the runtime you are *not*. This
is **review-only** — it never edits code or applies fixes.

## When NOT to use

- Inside another cross-check (the `CROSS_CHECK_ACTIVE` env marker is set). The
  helpers self-skip to prevent recursion; do not force past it.
- For trivial changes where an independent review adds nothing.

## Artifact types

- `code` — completed branch work. Compute the diff against the base first:
  base = `git merge-base HEAD <primary-branch>`; the review covers committed +
  staged + unstaged + untracked changes. Pass the diff as the artifact, and run
  from the worktree so the reviewer can read surrounding files (needed for the
  drift sweep). Record the scope you captured and pass it via `--scope`.
- `issue` — the issue/ticket draft markdown.
- `plan` — the plan markdown (file path or content).

## Workflow

1. **Identify the artifact and its type** (`code` / `issue` / `plan`). For
   `code`, build the diff as above.
2. **Detect routing.** The current runtime is known from the active overlay —
   see the platform overlay below. Probe the counterpart:

   ```bash
   cross-check/scripts/cross-check-detect.py --current-runtime <claude|codex>
   ```

   It reports `recommended_path` (`cross` or `fallback`). Detection is
   best-effort; the real fallback trigger is the cross run failing (step 3).
3. **Cross path** — run the counterpart read-only and capture the review:

   ```bash
   cross-check/scripts/cross-check-run.py \
     --current-runtime <claude|codex> \
     --artifact-type <code|issue|plan> \
     --artifact <path-or-omit-for-stdin> \
     --slug <kebab-case-summary> \
     --scope "<what was reviewed>"
   ```

   On success it writes `/tmp/cross-check-<slug>-<ts>.md` and prints the path +
   the review inline. **Exit codes:** `0` success; `3` recursion-skip (do
   nothing); `4` **fallback required** — the cross run failed (nonzero exit,
   empty output, or timeout), so perform the same-runtime fallback (step 4).
   Use `--dry-run` to preview the exact counterpart command without running it.
   If you had to trim a large artifact to fit, add `--truncated` so the review
   file is marked as based on partial context.
4. **Fallback path** (exit `4`, or `recommended_path: fallback`) — dispatch an
   **independent same-runtime** reviewer using the mechanism in the platform
   overlay, with the matching prompt from
   `cross-check/references/prompts/review-<type>.md`. The reviewer is read-only
   and returns review *text*; then render the file (labeled DEGRADED):

   ```bash
   echo "<review text>" | cross-check/scripts/cross-check-run.py \
     --current-runtime <claude|codex> --artifact-type <type> \
     --slug <slug> --render-only --mode degraded
   ```

5. **Soft gate.** Present the review inline. Then pause and require the operator
   to explicitly acknowledge or decide before proceeding past the trigger point.
   Do not auto-apply findings; do not edit. The gate is enforced by this
   session's workflow, not the OS.

Invoke the helpers by script path so approvals stay scoped to the script.

## Customization

Review prompts resolve through the `agent-plugins` convention (first match wins,
per file):

1. `<repo-root>/.agent-plugins/bento/bento/cross-check/prompts/review-<type>.md`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/cross-check/prompts/review-<type>.md`
   (default `~/.config/...` when `XDG_CONFIG_HOME` is unset)
3. The plugin-bundled default under `cross-check/references/prompts/`.

## Non-Negotiable Rules

- Review-only. The reviewer never edits code or writes patches; only this
  session writes the `/tmp` review file.
- The counterpart always runs read-only: Codex `--sandbox read-only`, Claude
  `--tools "Read,Grep,Glob" --permission-mode dontAsk`. Never grant write/exec.
- Always set `CROSS_CHECK_ACTIVE=1` for the reviewer (the runner does this) and
  always honor it as a skip on entry.
- A failed cross run falls back to the same-runtime reviewer; it does not block
  the workflow.
- Label same-runtime fallback output as DEGRADED.

## Stop conditions

- Both the counterpart and a same-runtime fallback are unavailable (no agent
  runtime usable): report that review was skipped and proceed, telling the
  operator no independent review was possible.
- The artifact type or scope is ambiguous: ask the operator which artifact to
  review.
