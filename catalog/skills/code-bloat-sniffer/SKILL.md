---
name: code-bloat-sniffer
description: |
  Use when the user wants to find code that can be removed, condensed,
  garbage-collected, or otherwise shrunk from a project. Scans the
  repo, dispatches per-chunk subagents in parallel, and produces a
  single markdown report of removal candidates with evidence per
  finding. Report-only — does not edit code or file tracker issues.
---

# Code-Bloat-Sniffer

Use this skill when the user asks to find code to remove, audit for
deletions, identify garbage to collect, look for things to remove, or
condense / shrink the codebase. This is a report-only skill: it
produces a markdown audit, never edits source, never files issues.

## Inputs

- `path` (optional) — defaults to the repo root.
- `focus` (optional) — free-text scope hint, e.g. "dead code only",
  "look in src/billing", "wide net". No enum.
- `output` (optional) — defaults to
  `/tmp/code-bloat-report-<repo-slug>-<timestamp>.md`.

## Workflow

1. **Inventory.** Detect stacks via manifests (`package.json`,
   `go.mod`, `pyproject.toml`, `Cargo.toml`, etc.) and file extensions.
   Map top-level dirs and stack modules. Establish exclusions:
   `vendor/`, `node_modules/`, `dist/`, `build/`, `target/`, `.next/`,
   generated directories, lockfiles, test fixtures.

2. **Chunk** the work by top-level subtree, or by stack module in
   monorepos. Polyglot repos: each chunk is a (subtree × stack) pair.

3. **Run repo-scoped tools.** Anything that needs the whole repo runs
   once here (dependency pruning, cross-package unused-export checks).
   Hold the output for the merge step.

4. **Dispatch chunks in parallel via
   `superpowers:dispatching-parallel-agents`.** This is the default,
   not a fallback. Only skip parallelism for trivially small targets
   (one small directory passed via `path`). Each subagent receives:
   - the chunk path,
   - the patterns guide
     (`code-bloat-sniffer/references/patterns.md`),
     loaded explicitly so it appears in the subagent's context,
   - the per-language tool list
     (`code-bloat-sniffer/references/tools-by-language.md`),
   - the finding contract (`## Finding contract`) it must follow when
     returning findings; each finding must carry all four evidence pieces.

5. **Aggregate** subagent findings into a single working list.

6. **Cross-chunk duplication pass.** Iterate the aggregated function
   signatures and shape hashes once. Group same-signature definitions
   across chunks; for each group with ≥ 2 members, read the bodies and
   confirm or reject semantic equivalence. Add confirmed duplicates as
   findings.

7. **Merge** repo-scoped tool output into the aggregated list (dedupe
   against per-chunk findings by file:line).

8. **Score and sort** by confidence × payoff:
   - **High** — tool agrees + manual evidence confirms + no
     dynamic-lookup risk.
   - **Medium** — manual evidence confirms; no tool agrees, or
     coverage is partial.
   - **Low** — heuristic match; all four evidence pieces present but
     negative-search coverage is shallow. Include only if `focus`
     widens the net.

   Payoff is LOC removable plus indirection collapsed (a one-caller
   wrapper counts more than its line count suggests).

9. **Write the report** to `output`. Echo the path. Done.

## Finding contract

Every finding must carry all four pieces. Drop findings missing any —
do not downgrade them.

1. **Exact location** — file path + line range; same for any
   referenced symbols.
2. **Negative-search evidence** — every search you ran (grep
   patterns, AST queries, dynamic-lookup scans) and its result. If
   you did not search, you did not look.
3. **Blast-radius statement** — public API vs module-private vs
   test-only vs flagged; estimated caller count.
4. **Proposed verification step** — concrete commands the
   implementer should run before merging the removal.

## Report format

Single markdown file:

```markdown
# Code Bloat Audit — <repo>
Generated: <ISO timestamp> · Scope: <path> · Stacks: <detected>

## Summary
- Findings: N (high: X, medium: Y, low: Z)
- Estimated LOC removable (high tier only): ~K
- Repo-scoped findings: <count>
- Largest clusters: <top 3 modules by finding count>

## Findings
### F1 · HIGH · path:line-line
**What:** ...
**Why removable:** ...
**Evidence:**
- search → result
- search → result
**Blast radius:** ...
**Verification before merge:** `command`
**Suggested action:** ...

### F2 · ...

## Skipped
- path/to/dir — reason
```

## Non-goals

This skill does not:

- edit source code,
- run tests itself,
- file tracker issues,
- remove dependencies,
- persist state across runs.

Filing findings as tracker issues is a separate workflow: feed the
report through `bento:issue-completeness-precheck` and then the
appropriate tracker flow skill (`bento:beads-issue-flow` or
`bento:github-issue-flow`).
