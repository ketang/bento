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
enforce.

**Where the guarantee actually lives.** The helper screens out commands that
obviously do nothing and refuses drafts it has not seen run. It resolves through
prefix commands (`timeout 5 …`, `sudo …`, `env -u FOO …`, `uv run …`) and shell
`-c` wrappers before screening, so a no-op hidden behind one is still caught.
Those are illustrations, not the list: the screen is a moving best-effort
heuristic, not an enumerated net, and it cannot be complete. Any command can be
a no-op — `git status`, `ls`, `make -f /dev/null`, a container image whose entry
point exits 0, a script whose body is commented out — and no static check can
prove a given command is this repo's gate. **The binding guarantee is you
confirming with the repo owner that the wired command is the real landing
gate.** Do not treat a clean `draft` as evidence that the command checks
anything.

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
   `--wrapper-path <rel>` to place the generated wrapper somewhere other than
   the default shown under **Output**. Nothing is installed yet.

   A bare command containing its own `::` (a pytest node id like
   `tests/test_x.py::test_case`, a cargo test path like `module::case`) can
   collide with the `NAME::COMMAND` split. A path-like segment before the
   first `::` is detected and treated as evidence of a bare command
   automatically; a slashless one (`module::case`) is not distinguishable
   from an intentional `NAME::COMMAND` and needs an explicit name to
   disambiguate: `--check 'citest::cargo test module::case'` (only the
   *first* `::` is ever treated as the separator, so the rest of the string
   is preserved whole).

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

   `apply` re-hashes the staged files and refuses unless they still match the
   receipt `validate` wrote, refuses a receipt with zero selected checks, and
   refuses to overwrite an existing wrapper or manifest without `--force`.

8. Commit both files. Tell the user land-work's verifier gate is now live.

## Output

```text
<worktree>/scripts/land-work-verifier.py            # or the --wrapper-path override
<worktree>/.agent-plugins/bento/bento/land-work/verifier.json
```

The manifest is repo-local and overrides any home-scope manifest under
`$XDG_CONFIG_HOME/agent-plugins/bento/bento/land-work/`. `verified_noop` starts
empty on a first wiring; add exemptions by hand only with a real per-path
reason. Re-wiring a repo that already has a manifest carries its existing
`verified_noop` entries forward and reports them as `carried_verified_noop` —
review them, since they suppress the gate for those paths.

Run every subcommand from the repo root. land-work reads the manifest from the
root only, so the helper refuses to run from a subdirectory rather than install
a manifest where the next landing would never find it.

`validate` never writes to the wrapper path. It runs its copy from a scratch
sibling in the same directory (`.land-work-verifier.<pid>.tmp.py`), which gives
the wrapper the same `REPO_ROOT` depth it will have once installed while leaving
any file already at the real path untouched — so re-wiring an already-wired repo
just works, and a `validate` killed mid-gate cannot strand a generated file over
something you wrote. Only `apply` writes to the real paths, and it refuses to
replace an existing wrapper or manifest — including a symlink — without
`--force`.

## Scope

- This is an on-ramp, not a loosening. It does not change land-work's
  fail-closed behavior when no manifest exists.
- It is not a CI-authoring tool. It wraps commands the repo already has; if the
  repo has no real gate, say so rather than inventing one.
- Contract details live in
  [`../land-work/references/project-verifier.md`](../land-work/references/project-verifier.md).
