---
name: compress-docs
description: |
  Use when the user wants to reduce the token footprint of documentation
  Claude ingests at session start. Scans CLAUDE.md, AGENTS.md, GEMINI.md,
  their referenced files, and user-global instructions; identifies
  duplication, dead references, and verbose prose; produces a reviewable
  compression plan with a preserved-claims guardrail.
---

# Compress-Docs

Use this skill to reduce the token footprint of documentation Claude
ingests at session start, without losing load-bearing content. This is
a meta-skill: it produces a reviewable plan, not immediate edits.

## When to use

- The user says "compress docs", "reduce documentation footprint",
  "trim CLAUDE.md", "shrink agent docs", "cut session-start context",
  or similar.
- The user notices their `CLAUDE.md` or related agent instructions have
  grown bloated, duplicated, or stale.
- Not for general documentation cleanup in `docs/` — this skill targets
  session-start context specifically. Historical design docs, ADRs, and
  changelogs are out of scope.

## Phases

1. **Discovery** — run the helper, read every in-scope file.
2. **Plan authoring** — draft the compression plan to
   `docs/specs/YYYY-MM-DD-compress-docs-plan.md`.
3. **Review gate** — present the plan, wait for the user to tick tier
   checkboxes.
4. **Apply** — pre-flight drift check, tier-by-tier edits, conditional
   backups, post-apply report.

## Phase 1: Discovery

Run the helper from the repository root:

```bash
compress-docs/scripts/compress-discover.py
```

Parse the JSON output. Use it as the deterministic base layer:

- `scope` — every file you will read, with its tier, bytes, lines, and
  `tokens_char4` count.
- `dead_references` — missing paths and missing commands, already
  classified. Every one is a delete candidate.
- `duplicate_blocks` — paragraphs appearing in 2+ files. Every one is a
  merge or delete candidate.
- `orphans` — nested `CLAUDE.md` files not referenced from anywhere
  else. Advisory only; flag in the plan summary but do not propose
  deletion without the user's explicit request.
- `token_baseline` — the "before" numbers for the savings report.

After parsing the helper output, read every file in `scope` in full.
Do not rely on the helper alone: the helper catches verbatim duplication
and dead references, but contradictions in different words and
verbose-but-correct prose require the model's own reading.

## Phase 2: Plan authoring

Before drafting the plan, load
`compress-docs/references/compression-rules.md`. Every
rule in that file is binding.

Write the plan to `docs/specs/YYYY-MM-DD-compress-docs-plan.md`, where
`YYYY-MM-DD` is today's date. Plan structure:

```
# Compress-Docs Plan — YYYY-MM-DD

## Summary
- Scope: N files across K tiers
- Baseline: ~X tokens
- Projected after: ~Y tokens (~Z% reduction)
- Per-tier breakdown:
  | Tier | Files | Before | After | Delta |
  |------|-------|--------|-------|-------|
  | 1 | ... | ... | ... | ... |

## Tier 1 — Project
### /abs/path/to/CLAUDE.md (~before → ~after tokens, -N%)
**Signals:** dead-refs=N, dup-blocks=N

**Preserved claims:**
- <bullet per distinct claim in the file>

**Proposed changes:**
1. DELETE lines A-B — dead-ref:<target>
   ```diff
   - <exact removed text>
   ```
2. REWRITE lines C-D — verbose
   ```diff
   - <exact before>
   + <exact after>
   ```
3. MERGE with /abs/path/to/other.md:X-Y — duplicate
   ```diff
   - <exact before>
   ```

## Tier 2 — Referenced
...

## Tier 3 — User-global
...

## Tier 4 — Memory
...

## Approval
- [ ] Apply Tier 1
- [ ] Apply Tier 2
- [ ] Apply Tier 3
- [ ] Apply Tier 4
```

Every change must cite a reason code from the taxonomy in
`compression-rules.md`. Every file section must include the full
preserved-claims list. Every diff must be literal — no summaries.

After writing the plan, tell the user:

> "Compression plan written to `<path>`. Review it, tick the tier
> checkboxes you want applied, optionally add `<!-- skip -->` next to
> any file section you want to exclude, then tell me to apply it."

Do not apply anything yet. Wait for explicit approval.
