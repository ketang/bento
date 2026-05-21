# `code-bloat-sniffer` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `bento:code-bloat-sniffer` — a polyglot bento skill that scans a project, produces one markdown report of removal candidates with evidence, and defaults to parallel fan-out via `superpowers:dispatching-parallel-agents`.

**Architecture:** One skill in `catalog/skills/code-bloat-sniffer/` with `SKILL.md` plus two reference files (`patterns.md`, `tools-by-language.md`). No helper script in v1. The skill's running agent handles inventory, dispatch, aggregation, and report writing using `Glob`/`Grep`/`Read`/`Bash`. Report-only; no source edits, no tracker filing, no cross-run state.

**Tech Stack:** Markdown (skill content). `scripts/build-plugins` (existing Python build) regenerates plugin output. `scripts/bump-plugin-versions` (existing) handles version arithmetic.

**Spec:** `docs/specs/2026-05-21-code-bloat-sniffer-design.md` (relocated as Task 1 of this plan).

---

### Task 1: Relocate design spec into the repo

**Files:**
- Create: `docs/specs/2026-05-21-code-bloat-sniffer-design.md`
- Source: `/home/ketan/.claude/plans/i-have-an-idea-i-encapsulated-barto.md`

- [ ] **Step 1: Copy the approved spec into the repo at its canonical path**

```bash
cp /home/ketan/.claude/plans/i-have-an-idea-i-encapsulated-barto.md \
   docs/specs/2026-05-21-code-bloat-sniffer-design.md
```

- [ ] **Step 2: Remove the "Spec Relocation on Implementation" footer from the in-repo copy**

That footer was a TODO to do this exact relocation. Open `docs/specs/2026-05-21-code-bloat-sniffer-design.md`. Delete the trailing section that begins with `## Spec Relocation on Implementation` through the end of the file.

- [ ] **Step 3: Verify**

```bash
test -f docs/specs/2026-05-21-code-bloat-sniffer-design.md && \
  ! rg -q "Spec Relocation on Implementation" docs/specs/2026-05-21-code-bloat-sniffer-design.md && \
  echo OK
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add docs/specs/2026-05-21-code-bloat-sniffer-design.md docs/plans/2026-05-21-code-bloat-sniffer-plan.md
git commit -m "docs: add code-bloat-sniffer design spec and implementation plan"
```

---

### Task 2: Scaffold the skill directory

**Files:**
- Create: `catalog/skills/code-bloat-sniffer/` (directory)
- Create: `catalog/skills/code-bloat-sniffer/references/` (directory)

- [ ] **Step 1: Create the skill directories**

```bash
mkdir -p catalog/skills/code-bloat-sniffer/references
```

- [ ] **Step 2: Verify**

```bash
test -d catalog/skills/code-bloat-sniffer/references && echo OK
```

Expected: `OK`

No commit yet — the directories are committed when files land inside them.

---

### Task 3: Write `references/patterns.md`

**File:** Create: `catalog/skills/code-bloat-sniffer/references/patterns.md`

Patterns first (before SKILL.md) so SKILL.md can point at concrete recipes that exist.

- [ ] **Step 1: Write the file**

Content:

````markdown
# Removable-Code Patterns

Narrative guide to what tends to be removable and how to find each kind. Not a rigid taxonomy. Use judgment.

Every finding must carry all four evidence pieces (see `SKILL.md`). If you cannot collect them, drop the finding rather than file a weak one.

## Unreferenced symbols (functions, classes, exports, files)

**Look for:** definitions where every search comes back empty.

**Searches to run before flagging:**
- `Grep` the symbol name across the whole scope (source, tests, configs, templates, docs, examples).
- Look for exports from any index/barrel file.
- Scan for dynamic lookups: string-based imports, `getattr`/`eval`/`hasattr`/reflection equivalents, `require()` with computed names, glob-loaded plugins.
- Check public API surface: package manifests, `__all__`, `exports` fields, OpenAPI/GraphQL schemas, generated bindings.

**Evidence required:** every search above plus its result.

**Blast radius cues:** module-private (safe) → package-internal → public API → external consumers in workspace siblings.

## Near-duplicates

**Look for:** functions with the same shape solving the same problem in two places.

**Searches to run:**
- Group functions by signature (parameter count + types + return type) within and across chunks.
- For same-signature groups, compare bodies. Tokens that match >70% by line count are candidates.
- Confirm semantic equivalence by reading both, not just by line similarity.

**Evidence required:** location of both, similarity ratio, semantic confirmation note, which one should survive (and why).

**Blast radius cues:** if one is in a library module and the other is a copy in a consumer, consolidate at the library. If both are in consumers, consider whether either belongs in shared code.

## Wrappers and indirections with ≤ 1 caller

**Look for:** functions, classes, interfaces, or modules whose only job is to forward to something else.

**Patterns:**
- Single-line wrapper functions.
- Interfaces with one implementation that no one mocks.
- Base classes with one subclass.
- Config options nothing sets.
- Plugin points with no third-party use.

**Searches to run:** caller count via `Grep`, plus a check that the wrapper adds no behavior (no validation, no logging, no error translation).

**Evidence required:** caller count, the wrapper body, what (if anything) it actually adds.

## Fully rolled-out feature flags

**Look for:** flag checks whose value has been pinned for a long time.

**Searches to run:**
- Locate flag definitions (look for the project's flag system: env vars, `LaunchDarkly`, `growthbook`, custom registries, `process.env.FEATURE_*`).
- For each flag, find every read site.
- Check the flag's defined default and any config files / dashboards in the repo.
- `git log -p` the flag-set sites to estimate how long the value has been stable.

**Evidence required:** flag name, definition site, all read sites, default value, last-changed date from git, recommended branch to keep.

## Finished migrations and version-compat shims

**Look for:** code labeled "legacy", "v1", "old", "compat", "transition", or dated comments.

**Searches to run:**
- `Grep` for `legacy|deprecated|TODO.*remove|v1|compat` across the scope.
- For each match, check whether the documented sunset condition has passed (often in a comment near the call site).
- Look for parallel implementations: `*_v2.py`, `*-new.ts`, `New<ClassName>`, etc., and check whether the old one is still called.

**Evidence required:** the marker, the condition for removal, evidence that the condition is met, callers of the deprecated path.

## Commented-out blocks

**Look for:** large blocks of code disabled by line or block comments.

Be conservative. Comment-outs sometimes preserve known-good fallbacks. Only flag blocks where:
- The block is older than 90 days in `git blame`, AND
- The block is not referenced from any nearby comment (e.g. "see disabled block above"), AND
- A working alternative is in the same file.

**Evidence required:** block location, age from blame, nearby context, the alternative.

## Dead dependencies

**Look for:** entries in `package.json` / `requirements.txt` / `go.mod` / `Cargo.toml` that no code imports.

**Searches to run:**
- For each declared dependency, `Grep` for its import name across the source tree.
- Distinguish runtime deps (`dependencies`) from dev deps; report both but mark separately.
- Check for transitive use via tool configs, lint configs, build scripts.

**Evidence required:** dependency name, no-imports search result, blast radius (dev vs runtime).

**Do not propose uninstalling.** Report only; the issue implementer runs the uninstall.
````

- [ ] **Step 2: Verify file exists and has the expected sections**

```bash
rg -c "^## " catalog/skills/code-bloat-sniffer/references/patterns.md
```

Expected: `7` (seven `##` sections — unreferenced, duplicates, wrappers, flags, migrations, commented-out, deps).

- [ ] **Step 3: Commit**

```bash
git add catalog/skills/code-bloat-sniffer/references/patterns.md
git commit -m "feat(code-bloat-sniffer): add removable-code patterns reference"
```

---

### Task 4: Write `references/tools-by-language.md`

**File:** Create: `catalog/skills/code-bloat-sniffer/references/tools-by-language.md`

Ship day one with TypeScript, Go, Python, Rust.

- [ ] **Step 1: Write the file**

Content:

````markdown
# Tools by Language

Optional language-specific tools the agent may shell out to if installed. Use these in addition to manual searches — they catch things grep misses, but they also produce false positives, so combine with the four evidence pieces.

Detect a language by manifest file at the chunk root, not by glob. A `package.json` makes the chunk TypeScript/JavaScript; `go.mod` makes it Go; `pyproject.toml` or `requirements.txt` makes it Python; `Cargo.toml` makes it Rust.

For each tool entry: what it finds, how to invoke, how to parse, what false positives to expect.

## TypeScript / JavaScript

### `knip`

**Finds:** unused files, exports, dependencies, types.

**Invoke:** `npx --yes knip --reporter json` from the chunk root.

**Parse:** top-level keys are `files`, `exports`, `types`, `dependencies`, `devDependencies`, `unlisted`. Each value is a list of locations.

**False positives:**
- Dynamic `import()` with computed paths.
- Files loaded by test runners not declared in config.
- Re-exports in barrels.

### `ts-prune`

**Finds:** exported symbols with no importers.

**Invoke:** `npx --yes ts-prune` from the chunk root (must have a `tsconfig.json`).

**Parse:** one line per finding: `path/to/file.ts:LINE - SymbolName (used in module)`. The `(used in module)` suffix means used internally — usually not removable.

**False positives:**
- Symbols re-exported from a public barrel.
- Symbols consumed by other workspaces in a monorepo (run per-package).

## Go

### `staticcheck`

**Finds:** unused variables, unreachable code, redundant code (U-series checks).

**Invoke:** `staticcheck ./...` from the chunk root.

**Parse:** lines of form `file.go:LINE:COL: message (Uxxxx)`. The `U`-prefixed codes are the unused-code checks.

**False positives:**
- Reflection-driven access (`reflect`).
- Code generated from build tags not enabled in the run.

### `go mod tidy` dry-run

**Finds:** unused modules in `go.mod`.

**Invoke:** copy `go.sum`/`go.mod` to a scratch dir, run `go mod tidy -v` there, diff against original.

**Parse:** any module that disappears from `go.mod` after tidy is a candidate.

**False positives:**
- Modules used only in build-tagged code that is not in the default build.

## Python

### `vulture`

**Finds:** unused functions, classes, imports, variables.

**Invoke:** `vulture --min-confidence 80 <chunk_root>`.

**Parse:** lines of form `path/file.py:LINE: unused <kind> '<name>' (NN% confidence)`.

**False positives:**
- Functions called by `getattr` / `__getattr__` / decorator registries.
- Test fixtures.
- Entry points declared in `pyproject.toml` / `setup.cfg`.

Always start at `--min-confidence 80`; lower confidences are noisy.

### `deadcode`

**Finds:** unused functions (modern alternative to vulture for newer Pythons).

**Invoke:** `deadcode <chunk_root>`.

**Parse:** lines of form `path/file.py:LINE: unused function ...`.

**False positives:** same dynamic-lookup risks as vulture.

## Rust

### `cargo +nightly udeps`

**Finds:** unused dependencies declared in `Cargo.toml`.

**Invoke:** `cargo +nightly udeps --workspace` from the chunk root. Requires nightly toolchain — skip the tool if unavailable.

**Parse:** sections per crate listing `unused crates in the dependencies table` and `unused crates in the dev-dependencies table`.

**False positives:**
- Crates used only behind feature flags not enabled in the run.

### `cargo clippy -W dead_code`

**Finds:** dead functions, dead structs, dead enum variants.

**Invoke:** `cargo clippy --workspace --all-targets -- -W dead_code 2>&1`.

**Parse:** lines of form `warning: function ... is never used` with a `--> path/file.rs:LINE` follow-up.

**False positives:**
- `#[allow(dead_code)]`-marked items (clippy still surfaces them sometimes — confirm).
- Items only used in test builds.
````

- [ ] **Step 2: Verify file exists and has four language sections**

```bash
rg -c "^## (TypeScript|Go|Python|Rust)" catalog/skills/code-bloat-sniffer/references/tools-by-language.md
```

Expected: `4`

- [ ] **Step 3: Commit**

```bash
git add catalog/skills/code-bloat-sniffer/references/tools-by-language.md
git commit -m "feat(code-bloat-sniffer): add per-language tool catalog (TS, Go, Python, Rust)"
```

---

### Task 5: Write `SKILL.md`

**File:** Create: `catalog/skills/code-bloat-sniffer/SKILL.md`

The user-facing skill content. Target under ~3,000 tokens per the project's "Be concise" guidance in `CLAUDE.md`.

- [ ] **Step 1: Write the file**

Content:

````markdown
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
   - the finding schema (below) it must return.

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
````

- [ ] **Step 2: Validate frontmatter parses**

```bash
python3 -c "
import yaml, re, sys
content = open('catalog/skills/code-bloat-sniffer/SKILL.md').read()
m = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
if not m:
    print('NO_FRONTMATTER'); sys.exit(1)
data = yaml.safe_load(m.group(1))
assert data['name'] == 'code-bloat-sniffer', data
assert 'description' in data
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Token sanity check**

Approximate token count (chars / 4):

```bash
wc -c catalog/skills/code-bloat-sniffer/SKILL.md | awk '{print int($1/4)}'
```

Expected: under ~3000. If over, trim.

- [ ] **Step 4: Commit**

```bash
git add catalog/skills/code-bloat-sniffer/SKILL.md
git commit -m "feat(code-bloat-sniffer): add SKILL.md entry point"
```

---

### Task 6: Rebuild plugin output

**Files:**
- Modify (generated): `plugins/**` (do not hand-edit; let `scripts/build-plugins` regenerate).

Per `AGENTS.md`: "If a skill changes, rebuild generated plugins with `scripts/build-plugins`."

- [ ] **Step 1: Run the build**

```bash
scripts/build-plugins
```

Expected: exit 0, no errors. New files added under `plugins/` corresponding to `code-bloat-sniffer`.

- [ ] **Step 2: Confirm the new skill appears in generated output**

```bash
find plugins -path '*code-bloat-sniffer*' -type f | head -10
```

Expected: at least one path under each generated plugin (Claude / Codex) containing the skill files.

- [ ] **Step 3: Commit generated output**

```bash
git add plugins/ .claude-plugin/marketplace.json .agents/plugins/marketplace.json
git commit -m "build: regenerate plugin output for code-bloat-sniffer"
```

If marketplace.json files were not changed, omit them from `git add`.

---

### Task 7: Version bump

Per `AGENTS.md`: any behavioral change to `catalog/skills/` requires a version bump via `scripts/bump-plugin-versions`, followed by another `scripts/build-plugins`.

- [ ] **Step 1: Run the bumper**

```bash
scripts/bump-plugin-versions
```

The script identifies which plugins changed and increments versions automatically.

- [ ] **Step 2: Rebuild after bump**

```bash
scripts/build-plugins
```

- [ ] **Step 3: Verify version updates appear in `catalog/plugin-versions.json` and generated manifests**

```bash
git diff --stat catalog/plugin-versions.json plugins/ | head -20
```

Expected: `catalog/plugin-versions.json` changed plus the corresponding generated manifests under `plugins/`.

- [ ] **Step 4: Commit**

```bash
git add catalog/plugin-versions.json plugins/ .claude-plugin/marketplace.json .agents/plugins/marketplace.json
git commit -m "chore: bump plugin version for code-bloat-sniffer"
```

Drop any path that did not change from the `git add`.

---

### Task 8: Smoke-test on bento itself

The realest test for a content-only skill is running it. Verify the skill is invokable and produces a well-formed report on a known target.

**Important:** The skill must be visible in the available-skills list before invocation. After Task 6 (`scripts/build-plugins`), the generated plugin files exist on disk, but a running Claude Code session has its skill list captured at session start. Start a new session, ideally with the skill cache refreshed, before Step 1.

- [ ] **Step 1: Invoke the skill via Claude Code in a fresh session, passing bento as the target**

From a fresh prompt (in this worktree, in a new session):

> "Use the code-bloat-sniffer skill to audit this repo. Path: `.`. Output: `/tmp/code-bloat-report-bento-smoke.md`."

The agent should fan out to parallel subagents per `dispatching-parallel-agents`, then aggregate.

If the skill is not yet visible to the new session, fall back to a manual simulation in the current session: read `catalog/skills/code-bloat-sniffer/SKILL.md`, `references/patterns.md`, and `references/tools-by-language.md`, then execute the workflow step-by-step against the bento repo.

- [ ] **Step 2: Inspect the report**

```bash
test -f /tmp/code-bloat-report-bento-smoke.md && head -50 /tmp/code-bloat-report-bento-smoke.md
```

Expected sections present in order:
1. Header (repo, timestamp, scope, stacks).
2. `## Summary` with counts by tier.
3. `## Findings` with at least one entry that has all four evidence pieces.
4. `## Skipped` with at least the expected exclusions (`plugins/`, `node_modules/` if present, etc.).

- [ ] **Step 3: Spot-check one high-tier finding by hand**

Pick one HIGH finding from the report. Confirm:
- The cited file and line range exist.
- The grep searches the report claims it ran really return what it says.

If a finding fails this check, the patterns guide or SKILL.md procedure is too loose — iterate before landing.

- [ ] **Step 4: No commit** (smoke artifacts live in `/tmp/`, not in repo)

---

### Task 9: Land

**Use the `bento:land-work` skill** to merge `code-bloat-sniffer` into `main` (no fast-forward, no squash, per the user's source-code-management guidance), close out the branch and worktree, and run post-extension hooks.

- [ ] **Step 1: Invoke `bento:land-work`**

Follow that skill's workflow end-to-end. It will:
- verify branch & worktree state,
- run `post` extension hooks,
- merge with an explicit merge commit,
- delete the linked worktree and branch after merge.

- [ ] **Step 2: Confirm `main` has the new skill**

After `bento:land-work` tears down the linked worktree, cd into the primary bento checkout (the first entry of `git worktree list`) and run:

```bash
git log --oneline main -5
ls catalog/skills/code-bloat-sniffer/
```

Expected: a merge commit referencing `code-bloat-sniffer`, and the skill directory present on `main`.

---

## Self-Review Checklist

Before declaring the plan complete, the executing agent (or planner) should
have addressed:

- [ ] Spec relocated and the in-repo copy has no "Spec Relocation"
      footer.
- [ ] `references/patterns.md` covers all seven pattern families.
- [ ] `references/tools-by-language.md` has all four day-one
      languages.
- [ ] SKILL.md frontmatter parses and `name` is `code-bloat-sniffer`.
- [ ] SKILL.md is under ~3,000 tokens (chars/4).
- [ ] `scripts/build-plugins` succeeds with no warnings.
- [ ] Version bump committed alongside regenerated plugin output.
- [ ] Smoke run on bento produced a report with all four evidence
      pieces for at least one HIGH finding.

## Test Suite Impact

No new tests are added to `tests/`. The skill is content-only; the
existing `scripts/build-plugins` is the integration check, and the
smoke test in Task 8 is the manual verification. State this
explicitly in the land-work summary per launch-work rule 12.
