---
schema_version: 1
title: Wire Land Verifier Scaffolds A Real Landing Gate
slug: wire-land-verifier-scaffold
status: active
authority: observed
change_resistance: high
tests_applicable: true
locked_sections:
  - Intent
---

# Wire Land Verifier Scaffolds A Real Landing Gate

## Intent
When a repository has no land-work verifier manifest, wire-land-verifier creates one from the repo's real, owner-confirmed gate command — never from a guessed or no-op command that would let a landing pass without checking anything.

## Story
A repo adopts `land-work` and hits its fail-closed verifier gate mid-landing: there is no `.agent-plugins/bento/bento/land-work/verifier.json`. The failure message names `bento:wire-land-verifier` as the remediation. Run ahead of the next landing, the skill runs `discover`, which reads Makefile targets, package.json scripts, justfile recipes, and single-line workflow `run:` steps, ranks "run everything" names above narrow ones, and writes nothing. The agent shows the ranked candidates and asks the user which one is this repo's actual landing gate. With that confirmation, `draft` stages a wrapper script and manifest — screening out commands that obviously do nothing (`true`, `echo`, `sh -c true`, `env true`, `python -c pass`) and commands whose executable does not resolve — and prints both bodies for review alongside a caveat stating that the screening is best-effort and that the binding guarantee is the owner's confirmation. `validate` runs the staged wrapper for real and records a receipt only when it emits schema-valid output with at least one selected check. `apply` re-hashes the staged files and installs them only when they still match the receipt, and refuses to clobber existing files without `--force`. The result satisfies `land-work-run-verifier.py` unchanged.

## Expected Behavior
- `discover` proposes candidates and writes nothing to the worktree.
- `draft` requires at least one explicit `--check`; it never selects a command on its own.
- Obvious no-op commands are rejected: bare `true`/`:`/`echo`/`exit`, shell wrappers around them including clustered flags (`bash -lc true`, `sh -cx true`, `sh -c -- true`), environment prefixes (`env true`, `nohup true`, `nice -n 5 true`), and trivial interpreter one-liners (`python3 -c pass`).
- This screening is explicitly best-effort, not a proof of non-triviality: `draft` reports a caveat saying so, because an arbitrary accepted command can still do nothing. The binding guarantee is the owner confirming the gate.
- `validate` executes the staged wrapper and exits nonzero unless it emits schema-valid output whose status is `passed`.
- `validate` refuses to stage over a pre-existing file at the wrapper path without `--force`, and with `--force` restores the original bytes and mode and removes directories it created.
- `apply` refuses without a validation receipt, refuses when the staged files no longer hash to the receipt's fingerprint (including tampering after validation), refuses on zero selected checks, and refuses to overwrite without `--force`.
- The generated manifest is `schema_version: 1`; `verified_noop` is empty on a first wiring and carries forward any entries an existing manifest already had, reported as `carried_verified_noop`.
- Every subcommand refuses to run from a subdirectory of the worktree, since land-work reads the manifest from the repo root only.

## Boundaries
- Does not weaken land-work's fail-closed behavior when no manifest exists.
- Does not auto-generate a manifest without explicit confirmation of the gate command.
- Not a CI-authoring tool: it wraps commands the repo already has rather than inventing a gate.
- Does not claim to detect every no-op command; it removes the obvious ones and defers the real judgment to the confirming owner.
- Does not change `land-work-run-verifier.py`'s contract.

## Auditable Claims
- `wire-land-verifier/scripts/wire-land-verifier.py` exposes `discover`, `draft`, `validate`, and `apply` subcommands.
- `draft` rejects commands that resolve to a no-op executable, including through shell and environment-prefix wrappers.
- `apply` recomputes the fingerprint from the staged wrapper, staged manifest, and wrapper path, and requires the validation receipt to match that recomputed value.
- The installed wrapper and manifest are accepted by `catalog/skills/land-work/scripts/land-work-run-verifier.py`.

## Evidence
### Tests
- `tests/wire_land_verifier/test_wire_land_verifier.py`
### Docs
- `catalog/skills/wire-land-verifier/SKILL.md`
- `catalog/skills/land-work/references/project-verifier.md`
