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
A repo adopts `land-work` and hits its fail-closed verifier gate mid-landing: there is no `.agent-plugins/bento/bento/land-work/verifier.json`. The failure message names `bento:wire-land-verifier` as the remediation. Run ahead of the next landing, the skill runs `discover`, which reads Makefile targets, package.json scripts, justfile recipes, and single-line workflow `run:` steps, ranks "run everything" names above narrow ones, and writes nothing. The agent shows the ranked candidates and asks the user which one is this repo's actual landing gate. With that confirmation, `draft` stages a wrapper script and manifest — refusing no-op commands like `true` or `echo` and commands whose executable does not resolve — and prints both bodies for review. `validate` runs the staged wrapper for real and records a receipt only when it emits schema-valid output with at least one selected check. `apply` installs the two files only against a receipt matching the current draft, and refuses to clobber existing files without `--force`. The result satisfies `land-work-run-verifier.py` unchanged.

## Expected Behavior
- `discover` proposes candidates and writes nothing to the worktree.
- `draft` requires at least one explicit `--check`; it never selects a command on its own.
- No-op commands (`true`, `:`, `echo`, `exit`, and shell wrappers around them) are rejected.
- `validate` executes the staged wrapper and exits nonzero unless it emits schema-valid output whose status is `passed`.
- `apply` refuses without a validation receipt, refuses when the draft changed after validation, refuses on zero selected checks, and refuses to overwrite without `--force`.
- The generated manifest is `schema_version: 1` with an empty `verified_noop`.

## Boundaries
- Does not weaken land-work's fail-closed behavior when no manifest exists.
- Does not auto-generate a manifest without explicit confirmation of the gate command.
- Not a CI-authoring tool: it wraps commands the repo already has rather than inventing a gate.
- Does not change `land-work-run-verifier.py`'s contract.

## Auditable Claims
- `wire-land-verifier/scripts/wire-land-verifier.py` exposes `discover`, `draft`, `validate`, and `apply` subcommands.
- `draft` rejects commands whose executable name is in the no-op denylist.
- `apply` requires a validation receipt whose fingerprint matches the current draft.
- The installed wrapper and manifest are accepted by `catalog/skills/land-work/scripts/land-work-run-verifier.py`.

## Evidence
### Tests
- `tests/wire_land_verifier/test_wire_land_verifier.py`
### Docs
- `catalog/skills/wire-land-verifier/SKILL.md`
- `catalog/skills/land-work/references/project-verifier.md`
