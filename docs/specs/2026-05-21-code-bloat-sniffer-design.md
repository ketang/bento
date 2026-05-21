# `bento:code-bloat-sniffer` — Design Spec (v1)

## Context

AI agents reliably generate more code and more documentation but rarely
condense, combine, garbage-collect, or remove code without risking
breakage. The user wants a bento skill that, when run against a project,
identifies opportunities to remove or shrink code, with enough evidence
per finding that a fresh agent could act on it safely.

v1 is deliberately small: one skill, report-only, no tracker filing, no
cross-run state, no source edits. Filing as tracker issues (via
`bento:issue-completeness-precheck` + a tracker flow skill) is named as
a follow-up but explicitly out of scope here.

## Goal

A single bento skill that scans a project end-to-end and produces one
markdown report of removal candidates with evidence. Parallel fan-out is
the default execution path.

## Non-Goals (v1)

- No source edits.
- No automated tracker filing.
- No persistent state across runs (no dedup of previously-reported findings).
- No linter-style opinions on style, naming, or complexity.
- No automatic dependency uninstalls.
- No per-stack specialized variants.

## Skill Family

**One skill.** Not multiple.

Location: `catalog/skills/code-bloat-sniffer/`

Name: `code-bloat-sniffer`.

Files:

- `SKILL.md` — trigger, inputs, procedure, output schema. Target under
  ~3,000 tokens per the project's "Be concise" guidance in
  `CLAUDE.md`.
- `references/patterns.md` — narrative guidance (~1 page) on patterns
  to look for: unreferenced symbols, near-duplicates, wrappers with ≤1
  caller, fully-rolled feature flags, finished migrations,
  version-compat shims, commented-out blocks, dead dependencies. Not a
  rigid taxonomy.
- `references/tools-by-language.md` — optional language-specific tools
  (knip, ts-prune, vulture, deadcode, staticcheck, etc.). Each entry:
  what it finds, how to invoke, how to parse its output.

## Trigger

SKILL.md description fires when the user asks to: find code to remove,
audit for deletions, identify garbage to collect, look for things to
remove, condense or shrink the codebase.

## Inputs (all optional)

- `path` — defaults to repo root.
- `focus` — free-text scope/category hint. No enum.
- `output` — defaults to
  `/tmp/code-bloat-report-<repo-slug>-<timestamp>.md`. In-repo path
  (e.g. `docs/audits/...`) is supported but not default.

## Procedure

1. **Inventory.** Detect stacks via manifests and extensions. Map
   top-level dirs and stack modules. Establish exclusions: `vendor/`,
   `node_modules/`, `dist/`, `build/`, `target/`, `.next/`, generated
   directories, lockfiles, test fixtures.
2. **Chunk** the work by top-level subtree, or by stack module in
   monorepos. Polyglot repos: chunks are (subtree × stack) pairs.
3. **Run repo-scoped tools.** Anything that must see the whole repo
   runs once at this step (dependency pruning, cross-package
   unused-export checks). Capture output.
4. **Dispatch chunks in parallel via
   `superpowers:dispatching-parallel-agents`.** Default path, not a
   fallback. The only exception is trivially small targets (e.g. a
   single small directory passed via `path`). Each subagent receives:
   chunk path, the patterns guide, the per-language tool list, and the
   finding schema it must return.
5. **Aggregate** subagent findings.
6. **Cross-chunk duplication pass.** Coordinator (the agent itself,
   post-fan-in) runs one pass over function signatures and hashes
   collected from each chunk to surface duplicates no single chunk
   could see.
7. **Merge** repo-scoped tool output into the aggregated findings.
8. **Score and sort** by confidence × payoff. Payoff is estimated LOC
   removable plus indirection collapsed (e.g. a one-caller wrapper
   counts more than its line count suggests). Three confidence tiers:
   - **High** — tool agrees + manual evidence confirms + no
     dynamic-lookup risk.
   - **Medium** — manual evidence confirms; no tool agrees, or
     coverage is partial.
   - **Low** — heuristic match; all four evidence pieces present but
     negative-search coverage is shallow. Included only if `focus`
     widens the net.
9. **Write report** to `output`. Echo the path. Done.

## Finding Contract (every finding carries)

Findings missing any of the four are dropped, not downgraded:

1. **Exact location** — file path + line range; same for any
   referenced symbols.
2. **Negative-search evidence** — the actual searches run (grep
   patterns, AST queries, dynamic-lookup scans) and their results.
3. **Blast-radius statement** — public API vs module-private vs
   test-only vs flagged; estimated caller count.
4. **Proposed verification step** — concrete commands the implementer
   should run before merging the removal.

## Output Schema

Single markdown file:

- Header: repo, ISO timestamp, scope, detected stacks.
- `## Summary`: counts by tier, estimated LOC removable (high tier
  only), top clusters by finding count.
- `## Findings`: sorted by tier then payoff. Each entry: tier,
  location, what, why removable, evidence (bulleted), blast radius,
  verification, suggested action.
- `## Skipped`: chunks the agent bailed on (e.g. generated dirs,
  unreadable files), with reason. Coverage transparency.

## Critical Files (to create)

- `catalog/skills/code-bloat-sniffer/SKILL.md`
- `catalog/skills/code-bloat-sniffer/references/patterns.md`
- `catalog/skills/code-bloat-sniffer/references/tools-by-language.md`

## Reused

- `superpowers:dispatching-parallel-agents` — parallel fan-out.
- Standard Claude Code tools: `Grep`, `Glob`, `Read`, `Bash`.
- `catalog/skills/compress-docs/` is the structural model for size,
  references-directory shape, and tone — same family, different
  artifact.

## Out of Scope for v1 (named follow-ups)

- Tracker filing via `bento:issue-completeness-precheck` plus
  `bento:beads-issue-flow` or `bento:github-issue-flow`.
- Cross-run dedup so previously-filed findings are not re-reported.
- An `apply` mode that performs deletions and verifies with the
  project's test suite.
- Per-stack specialized variants if pattern coverage proves
  insufficient.

## Verification (how to test the skill itself)

1. Run `code-bloat-sniffer` on `bento` itself. Inspect the report; spot-check
   one high-tier finding by hand.
2. Run on a TypeScript project that has `knip` installed; verify
   high-tier findings agree with `knip` output.
3. Run on a small Python project with `vulture` installed; verify
   mid/high findings line up.
4. Take one high-tier finding from any run and confirm safety by
   removing the code on a scratch branch and running the project's
   tests.
5. Check that the `## Skipped` section accurately reflects excluded
   paths.

## Day-One Decisions

- Default report path: `/tmp/code-bloat-report-<repo-slug>-<timestamp>.md`.
  Caller may pass an explicit `output` path to override.
- `references/tools-by-language.md` ships day one with TypeScript, Go,
  Python, and Rust populated. Other languages grow on demand. Each
  entry documents: what the tool finds, how to invoke it, how to parse
  its output, and what false positives to expect.

