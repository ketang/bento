# compress-docs — Design

Status: draft
Author: Ketan Gangatirkar (with Claude)
Date: 2026-04-11

## Problem

Every Claude Code session in a project ingests a set of documentation files at
start time: `CLAUDE.md` at user-global and project levels, `AGENTS.md`,
`GEMINI.md`, nested `CLAUDE.md` files, and anything those docs reference. This
context is paid for in tokens on every session, and it drifts over time —
duplicated rules across files, stale references to renamed code, verbose
phrasing that could be tighter, and sections that were load-bearing once but
have been superseded.

There is currently no tool that identifies this rot and compresses it while
preserving meaning. The goal is a skill that does exactly that, targeted at
the session-start context that actually costs tokens, with guardrails strong
enough that users trust it to edit their agent instructions.

## Goals

- Identify duplication, dead references, contradictions, and verbose-but-
  correct prose across agent-facing docs.
- Produce a reviewable plan that preserves every distinct claim in the
  original docs while cutting byte count.
- Apply the plan with a review gate, drift detection, and blast-radius-aware
  ordering.
- Report honest token savings against a `char/4` baseline.

## Non-goals

- Command-drift detection (does `npm test` actually work as documented?).
  Out of scope; `generate-audit` already covers this.
- Git-age heuristics for "old therefore stale." Too many false positives.
- Rewriting code comments or source files. Markdown only.
- Committing or pushing changes. The skill leaves a dirty working tree; the
  user commits with their normal flow.
- Touching documentation that is not in the session-start ingest path.
  Historical design docs, ADRs, and changelogs are explicitly excluded.

## Scope

The skill operates across four **blast-radius tiers**. A single plan covers
all tiers; approval happens tier-by-tier.

| Tier | Contents | Blast radius |
|------|----------|--------------|
| 1 | `./CLAUDE.md`, `./AGENTS.md`, `./GEMINI.md`, all nested `CLAUDE.md` under repo | Current repo only |
| 2 | Files referenced from tier-1 docs via markdown links or backticked paths, walked transitively from tier-1 roots (depth 0) to depth 3, de-duped. Same definition of "reference" as the helper's dead-ref detector. | Current repo |
| 3 | `~/.claude/CLAUDE.md` | Every project this user works in |
| 4 | `~/.claude/projects/<slug>/memory/*.md` where `<slug>` is derived from `$PWD` | Current project's persistent memory |

## Architecture

A new skill at `catalog/skills/compress-docs/` following the `generate-audit`
meta-skill pattern:

```
compress-docs/
├── SKILL.md                     # procedure the model follows
├── scripts/
│   └── compress-discover.py     # deterministic helper
└── references/
    └── compression-rules.md     # loaded when the model writes the plan
```

Workflow:

1. Model invokes `compress-discover.py`, gets JSON describing scope files,
   dead references, duplicate paragraph blocks, token baselines.
2. Model reads every in-scope file whole and drafts a compression plan.
3. Plan is written to `docs/specs/YYYY-MM-DD-compress-docs-plan.md`.
4. User ticks tier-approval checkboxes in the plan file.
5. User says "apply," model runs the apply loop.
6. Model writes a post-apply report alongside the plan.

Trigger is description-matched, not a slash command. Model guidance: default
model (this skill is lighter than `generate-audit` — no cross-stack inference
or audit-module decisions).

## Component: `compress-discover.py`

Invoked by path, emits JSON to stdout. No judgment calls; deterministic
signals only.

### Scope resolution

Walks the four tiers, records each file with absolute path, tier number,
byte size, line count, and approximate token count using
`char/4` (`len(text) // CHARS_PER_TOKEN_ESTIMATE`, where
`CHARS_PER_TOKEN_ESTIMATE = 4`).

Rationale for `char/4` over `tiktoken`: empirical testing across 576
markdown files in the user's project tree showed an aggregate delta of
-0.3% between `char/4` and `tiktoken.cl100k_base`. Per-file deltas have a
wider spread (43% of files within ±5%, 11% beyond ±20%), but the outliers
cancel in aggregate. The skill's headline number ("total tokens saved") is
accurate; per-file annotations can be off ±30% at the extremes, which is
acceptable because the user makes decisions from the diff, not the savings
number.

Tier 2 traversal: tier-1 files are depth 0; files referenced from them are
depth 1; and so on. Hard cap at depth 3. Links are followed if and only if
the target resolves inside the current repository. A "reference" uses the
same definition as the `dead_references` detector below: markdown link
targets and backticked paths.

Contradiction detection is explicitly **not** a helper responsibility. The
helper surfaces duplicate paragraph blocks (verbatim or near-verbatim);
subtler contradictions — two files saying incompatible things in different
words — are identified by the model during its whole-file read and encoded
in the plan using the `contradicted-by:<file>` reason code.

### Deterministic signals

1. **`dead_references`** — for every backticked path, `~/...` path, shell
   command name, and markdown link target mentioned in any in-scope doc,
   attempt to resolve against the filesystem (`os.path.exists`), the repo's
   tracked files (`git ls-files`), and the user's `$PATH` (for command
   names). Emit misses with source file and line number.

2. **`duplicate_blocks`** — paragraph-level hashing. For each in-scope file,
   split on blank lines into paragraphs, normalize whitespace, require
   minimum 3 lines per paragraph, hash each paragraph, and emit hashes that
   appear in 2+ files. Each entry includes all file+line-range occurrences.

3. **`orphans`** — tier-1 files that are neither auto-loaded nor referenced
   from any other in-scope doc. Soft signal, listed in JSON but the model
   treats them as advisory only.

4. **`token_baseline`** — per-file counts, per-tier subtotals, and overall
   total. This is the "before" number for the savings report.

### Explicitly skipped

- Command validity / dry-run execution
- Git blame / file-age analysis
- Semantic similarity across non-duplicate paragraphs
- External reference checks (anything outside the current repo except
  tiers 3 and 4)

### Output format

Single JSON document:

```json
{
  "scope": [
    {
      "path": "/abs/path/to/CLAUDE.md",
      "tier": 1,
      "bytes": 4231,
      "lines": 98,
      "tokens_char4": 1057
    }
  ],
  "dead_references": [
    {
      "source": "/abs/path/to/CLAUDE.md",
      "line": 42,
      "reference": "scripts/old-tool.sh",
      "kind": "path",
      "resolution": "missing"
    }
  ],
  "duplicate_blocks": [
    {
      "hash": "a1b2...",
      "occurrences": [
        {"path": "/abs/path/to/CLAUDE.md", "start": 12, "end": 18},
        {"path": "/abs/path/to/AGENTS.md", "start": 30, "end": 36}
      ]
    }
  ],
  "orphans": ["/abs/path/to/nested/CLAUDE.md"],
  "token_baseline": {
    "per_file": {"/abs/path/to/CLAUDE.md": 1057},
    "per_tier": {"1": 3421, "2": 1820, "3": 988, "4": 412},
    "total": 6641
  }
}
```

## Component: compression plan

After the helper runs and the model reads every in-scope file whole, the
model writes a plan to `docs/specs/YYYY-MM-DD-compress-docs-plan.md`.

### Document structure

```markdown
# Compress-Docs Plan — 2026-04-11

## Summary
- Scope: 14 files across 4 tiers
- Baseline: ~6,641 tokens
- Projected after: ~4,120 tokens (~38% reduction)
- Per-tier breakdown: <table>

## Tier 1 — Project

### /abs/path/to/CLAUDE.md  (~1,057 → ~620 tokens, -41%)

**Signals:** dead-refs=2, dup-blocks=1

**Preserved claims:**
- Rule: plan mode is the default for non-trivial tasks
- Rule: use subagents liberally
- File convention: spec files live in docs/specs/
- <...every distinct rule/fact the model found in this file...>

**Proposed changes:**

1. DELETE lines 12-14 — dead-ref:scripts/old-tool.sh
   ```diff
   - Run `scripts/old-tool.sh` before committing to verify the build.
   - This script lives at the repo root and is the canonical pre-commit
   - verification step.
   ```

2. REWRITE lines 30-38 — verbose
   ```diff
   - When you encounter a bug, please take care to ensure that you have
   - fully understood the root cause before attempting a fix. Do not
   - attempt to fix the bug until you have verified the root cause by
   - reading the relevant source code and, if possible, writing a test
   - that reproduces the bug. Only then should you proceed to implement
   - a fix for the bug.
   + For bugs: find root cause first, write a reproducing test, then fix.
   ```

3. MERGE with /abs/path/to/AGENTS.md:50-56 — duplicate
   <...>

### /abs/path/to/AGENTS.md  (~880 → ~612 tokens, -30%)
<...>

## Tier 2 — Referenced
<...>

## Tier 3 — User-global
<...>

## Tier 4 — Memory
<...>

## Approval
- [ ] Apply Tier 1
- [ ] Apply Tier 2
- [ ] Apply Tier 3
- [ ] Apply Tier 4
```

### Format rules enforced by `compression-rules.md`

1. **Every change has a one-line reason** from a fixed taxonomy:
   `duplicate`, `dead-ref`, `verbose`, `outdated`, `contradicted-by:<file>`,
   `merge-target:<file>`. No free-form paragraphs.

2. **Every file section has a Preserved claims list.** This is the model's
   explicit inventory of the distinct rules and facts the file contains,
   regardless of whether the model proposes to touch them. It is the
   primary guardrail against silent loss of load-bearing content: the
   reviewer checks this list against the diff, and if a claim in the list
   doesn't appear in the post-apply file, that's a regression.

3. **Diffs are literal** — actual before/after text, not summaries. Review
   must be substantive.

4. **Per-file approval granularity** is at the file-section level within a
   tier. Reviewer skips a file by deleting its section or adding
   `<!-- skip -->` next to the heading before approving the tier.

### Approval mechanism

Tier-level checkboxes in the plan file. User edits the plan, ticks
approved tiers, then tells Claude to apply. Rationale: persists the
decision in the file (auditable), survives session compaction, and makes
per-file skipping a matter of editing the same document.

## Component: apply loop

Triggered when the user says "apply" (or similar) after checkboxes are
ticked.

### Procedure

1. **Re-read the plan file.** Parse tier checkboxes. Any unticked tier is
   skipped entirely. Any file section marked `<!-- skip -->` is skipped.

2. **Pre-flight drift check.** For every file the plan will touch, confirm
   that every `DELETE`/`REWRITE` hunk's "before" text still matches the
   current file content. If any file has drifted — because it was edited
   between plan generation and apply — abort the entire run and report
   which files drifted. No partial applies.

3. **Apply tier-by-tier in order 1 → 2 → 3 → 4.** Within each tier, files
   in path-sorted order for determinism. For each file:
   - Read current content.
   - Apply DELETEs and REWRITEs via the Edit tool's exact-match semantics.
   - Measure post-edit token count; if it deviates from the plan's
     projection by more than ±5%, record a soft warning (not an abort).

4. **MERGE operations run last within each tier.** When the plan says
   "merge file A:lines into file B," do the insert-into-B and
   delete-from-A as a pair. If the merge target is in a higher tier,
   defer the merge to when that tier runs.

5. **Conditional backup.** For every file the plan will touch, run
   `git -C <file_dir> ls-files --error-unmatch <file>`. If the file is
   tracked by some git repo (current repo, dotfiles repo, anything), skip
   the backup. If not, write `<file>.pre-compress-<timestamp>.bak` next to
   the file before applying changes. In practice this means tier 1 and
   tier 2 files almost always skip the backup (they are checked into the
   current repo), while tier 3 and tier 4 files typically get one unless
   the user keeps their dotfiles in a git repo. The check runs per-file,
   not per-tier, so a `.gitignored` tier-2 file still gets its backup.

6. **Write the post-apply report** to
   `docs/specs/YYYY-MM-DD-compress-docs-report.md`. Contents:
   - Actual baseline token count
   - Actual post-apply token count
   - Per-file delta (plan projection vs. actual)
   - Any drift aborts
   - Any ±5% soft warnings
   - Any skipped tiers and files
   - Paths of any backup files written

7. **No commits, no pushes.** Leave the working tree dirty.

## Safety summary

| Mechanism | Prevents |
|-----------|----------|
| Review gate (tier checkboxes) | Surprise edits |
| Preserved claims list per file | Silent loss of load-bearing content |
| Pre-flight drift check | Stale plans overwriting newer edits |
| Blast-radius tier ordering | User sees narrow-scope results before broad-scope changes land |
| Conditional backup for tier 3/4 | Loss of non-versioned global/memory files |
| Literal diffs in plan | Shallow review |
| One-line reason taxonomy | Justification by vague narrative |

## Testing

**Unit tests for the helper.** Follow the repo convention established by
`tests/generate_audit/test_audit_discover.py`: a `unittest.TestCase` that
builds a temporary git repository per test, seeds fixture files, runs the
helper script, and asserts on the parsed JSON output. Tests live at
`tests/compress_docs/test_compress_discover.py` and run under the
existing `python3 -m unittest discover -s tests -t .` command.

Test coverage targets one test per deterministic signal:

1. Scope resolution — tiers 1 and 2 discovered correctly, tier 2 depth
   cap enforced, out-of-repo references excluded.
2. Dead-reference detection — missing paths, missing commands, and
   existing paths all classified correctly.
3. Duplicate-block detection — identical paragraphs across two files
   flagged; paragraphs under the 3-line minimum ignored.
4. Orphan detection — unreferenced nested `CLAUDE.md` flagged; referenced
   ones not.
5. Token baseline — per-file, per-tier, and total counts match
   `len(text) // 4` on the fixture content.

Tier 3 and tier 4 tests use temporary directories with monkey-patched
`$HOME` so the helper treats them as the user-global and memory tiers
without touching the real `~/.claude/`.

**End-to-end manual verification** (not automated in CI, but documented
in the plan as a checklist):

1. Run the skill against a hand-crafted fake project with seeded
   duplication, dead references, and verbose passages.
2. Verify the plan identifies each seeded problem and that `Preserved
   claims` covers every distinct rule in the fixtures.
3. Drift test: edit a fixture file between plan and apply, confirm apply
   aborts with a drift report.
4. Tier 3 backup test: point the skill at an untracked fake
   `~/.claude/CLAUDE.md`, confirm a `.bak` is written before apply.

## Open questions

None at time of writing. All decisions made during brainstorming are
captured above.
