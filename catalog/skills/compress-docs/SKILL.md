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

## Phase 3: Review gate

Wait for the user to say "apply" (or similar) after editing the plan.
When they do, re-read the plan file to capture any edits — the user may
have ticked checkboxes, added `<!-- skip -->` markers, or edited
individual file sections.

## Phase 4: Apply

### Step 1: Parse approval state

Read the plan file. For each tier heading, find the corresponding
checkbox in the Approval section:

- `- [x] Apply Tier N` → tier N is approved
- `- [ ] Apply Tier N` → tier N is skipped entirely

Within each approved tier, for each `### /abs/path/...` file heading,
check whether `<!-- skip -->` appears on or immediately after the
heading line. If so, skip that file.

### Step 2: Pre-flight drift check

For every DELETE and REWRITE in the approved, non-skipped file sections,
verify the "before" text from the diff still matches the current file
content exactly. Any mismatch aborts the entire run.

If any file has drifted, report:

> "Apply aborted: the following files were edited after the plan was
> written and no longer match the proposed changes. Regenerate the plan
> to pick up the new content:
> - <file 1>
> - <file 2>
> ..."

Do not apply anything partially.

### Step 3: Apply tier by tier

Process tiers in order 1 → 2 → 3 → 4. Within each tier, process files
in path-sorted order. For each file:

1. For each DELETE or REWRITE in the file section, apply it using the
   Edit tool with the diff's "before" as `old_string` and the diff's
   "after" as `new_string` (empty string for DELETEs).
2. After all single-file edits land, measure the new token count.
   Compare against the plan's projection. If the actual count differs
   by more than ±5%, record a soft warning for the post-apply report.
3. MERGE operations run last within the tier. For each MERGE, insert
   the content into the target file at the specified location, then
   delete the content from the source file. If the target file is in a
   higher tier, defer the merge to when that tier runs.

### Step 4: Conditional backups

For every file touched in any tier, run:

```bash
git -C <file_parent_dir> ls-files --error-unmatch <file_basename>
```

If exit code is 0, the file is tracked by some git repo — skip the
backup. If exit code is non-zero, the file is not under version control;
before applying any edits to it, copy it to
`<file>.pre-compress-<timestamp>.bak` where `<timestamp>` is
`YYYYMMDD-HHMMSS` in UTC.

This check runs per-file, not per-tier. Backups are created before any
edit lands on a given file, so the user has a restore path for
non-versioned files.

### Step 5: Write the post-apply report

After all approved tiers finish, write
`docs/specs/YYYY-MM-DD-compress-docs-report.md` containing:

- Actual baseline token count (from the plan)
- Actual post-apply token count (re-measured from disk)
- Total delta and percentage
- Per-file table: planned delta vs. actual delta
- Any ±5% soft warnings
- Any tiers that were skipped
- Any files that were skipped via `<!-- skip -->`
- Paths of any backup files written
- Any drift aborts (if partial progress was made, though the skill
  should not make partial progress)

Tell the user:

> "Applied. Report written to `<path>`. Review the diff with your
> normal git workflow and commit when you're satisfied. Non-versioned
> files have backups at `<path>.pre-compress-<timestamp>.bak` — delete
> those once you've verified the edits."

### Hard rules

1. Never commit, stage, or push. The skill leaves the working tree
   dirty.
2. Never touch files outside the discovered scope.
3. Never rewrite source code files or non-markdown content.
4. Never apply without an explicit user "apply" signal after the plan
   is written.
5. Never skip the drift check.
6. Never apply tier 3 or tier 4 edits without running the per-file
   backup check first.
