---
name: wire-land-verifier
description: Scaffold land-work's project verifier for a repository — discover candidate gate commands, confirm the real one with the repo owner, then generate and install `.agent-plugins/bento/bento/land-work/verifier.json` plus its wrapper script. Use when a repo has no verifier manifest yet, or when `land-work` reports a missing one.
---

# Wire Land Verifier

`land-work` fails closed when a repo has no project verifier manifest. Run this
once, ahead of any landing, to create one.

**Never rubber-stamp.** The generated verifier must wrap the repo's real gate
command(s), confirmed by the repo owner. A verifier that reports `passed`
without running the repo's checks defeats the guarantee land-work exists to
enforce. The helper refuses no-op commands and unproven drafts, but it cannot
tell a wrong-but-real command from a right one — that judgment is yours and the
user's.

## Workflow

1. Identify the target worktree. Default to the current repo root.
2. Propose candidates (writes nothing):

   ```bash
   wire-land-verifier/scripts/wire-land-verifier.py discover
   ```

   It reads `Makefile` targets, `package.json` scripts, `justfile` recipes, and
   single-line `run:` steps in `.github/workflows/*.yml`, ranking
   "run everything" names above narrow ones.

3. **Confirm before drafting.** Show the ranked candidates and ask which
   command(s) are this repo's real landing gate — `AskUserQuestion` when
   interactive. Never pick one silently, even when discovery returns exactly one
   candidate. If discovery finds nothing, ask the user for the command. Prefer
   the aggregate gate (CI equivalent) over a single narrow step.
4. Stage the wrapper and manifest for review:

   ```bash
   wire-land-verifier/scripts/wire-land-verifier.py draft --check 'NAME::COMMAND' [--check ...]
   ```

   `--check` (required) is repeatable; a bare `COMMAND` names itself. Use
   `--wrapper-path <rel>` to override the default
   `scripts/land-work-verifier.py`, or to reuse a wrapper the repo already has.
   Nothing is installed yet.

5. Show the user the drafted `wrapper_body` and `manifest_body`.
6. Prove the draft actually runs:

   ```bash
   wire-land-verifier/scripts/wire-land-verifier.py validate
   ```

   Exit 0 means the wrapper emitted schema-valid output with at least one passed
   check. Nonzero with `"schema_valid": true` and `"status": "failed"` means the
   wrapper works but the repo's gate is currently red — a legitimate thing to
   wire, but confirm that with the user first. `"schema_valid": false` is a bug
   in the selected command; fix it and re-draft.

7. Install only after explicit user go-ahead:

   ```bash
   wire-land-verifier/scripts/wire-land-verifier.py apply
   ```

   `apply` refuses without a validation receipt matching the current draft, and
   refuses to overwrite an existing wrapper or manifest without `--force`.

8. Commit both files. Tell the user land-work's verifier gate is now live.

## Output

```text
<worktree>/scripts/land-work-verifier.py            # or the --wrapper-path override
<worktree>/.agent-plugins/bento/bento/land-work/verifier.json
```

The manifest is repo-local and overrides any home-scope manifest under
`$XDG_CONFIG_HOME/agent-plugins/bento/bento/land-work/`. `verified_noop` starts
empty; add exemptions by hand only with a real per-path reason.

## Scope

- This is an on-ramp, not a loosening. It does not change land-work's
  fail-closed behavior when no manifest exists.
- It is not a CI-authoring tool. It wraps commands the repo already has; if the
  repo has no real gate, say so rather than inventing one.
- Contract details live in
  [`../land-work/references/project-verifier.md`](../land-work/references/project-verifier.md).
