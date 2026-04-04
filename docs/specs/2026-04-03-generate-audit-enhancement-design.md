# Design: generate-audit Enhancement
**Date:** 2026-04-03
**Status:** Approved

## Goal

Upgrade `generate-audit` to produce audits that hold code to a high standard for
maintainability, clarity, quality, and design — and to inject static analysis
capabilities (linters, security analyzers, complexity tools, anti-pattern detectors)
into every generated audit, whether or not the repo already has tooling in place.

---

## Architecture

Two existing files change, two new reference files are added:

```
generate-audit/
  SKILL.md                              ← updated orchestration layer
  scripts/
    audit-discover.py                   ← extended with static_analysis block
  references/
    quality-standards.md                ← NEW: thresholds + code smell catalog
    static-analysis-tools.md            ← NEW: tool catalog by stack
```

**Data flow:**
1. `audit-discover.py` runs → emits JSON including new `static_analysis` block
2. SKILL.md instructs the model to load both reference docs during discovery
3. Model builds audit with: detected tools (run + interpret output), recommended
   missing tools, model-based quality review, concrete thresholds and smells from
   the standards reference
4. Generated audit has a dedicated **Static Analysis** phase (runs commands) and
   a **Code Quality** phase (thresholds + smell detection by model)

---

## Section 1: `audit-discover.py` changes

A new `detect_static_analysis_tools()` function emits a `static_analysis` block:

```json
"static_analysis": {
  "detected_tools": [
    { "tool": "eslint", "config": ".eslintrc.json", "run": "npx eslint . --format=compact" },
    { "tool": "golangci-lint", "config": ".golangci.yml", "run": "golangci-lint run ./..." },
    { "tool": "ruff", "config": "pyproject.toml", "run": "ruff check ." }
  ],
  "missing_by_language": {
    "Go": ["golangci-lint", "govulncheck"],
    "TypeScript": ["eslint", "knip"],
    "Python": ["ruff", "bandit", "mypy"]
  }
}
```

**Detection approach:** Script checks config file existence only (deterministic).
The model reads and interprets config contents (settings, disabled rules, raised
thresholds) during discovery.

**Tool detection map:**

| Category | Go | TypeScript/JS | Python | Rust |
|---|---|---|---|---|
| Linter | golangci-lint, staticcheck | eslint, biome, oxlint | ruff, pylint | clippy |
| Security | govulncheck, gosec | eslint-plugin-security, npm/pnpm audit | bandit, safety | cargo-audit |
| Secrets | gitleaks, trufflehog, detect-secrets | ← same (cross-language) | ← same | ← same |
| Complexity | golangci-lint (gocyclo, gocognit), lizard | eslint complexity rule, lizard | radon, wily, lizard | clippy |
| Dead code | golangci-lint (unused), deadcode | knip, ts-prune | vulture | clippy |
| Types | — | tsc --noEmit | mypy, pyright | — |
| Formatting | gofmt | prettier | ruff format | rustfmt, cargo fmt |
| Duplication | dupl, jscpd | jscpd | jscpd | jscpd |
| Dep health | go list -u -m all, nancy | npm outdated, depcheck, license-checker | pip-audit, pip-licenses | cargo outdated |
| Coverage | go test -coverprofile | vitest/jest --coverage | pytest --cov | cargo tarpaulin |
| Doc coverage | golint / godot (in golangci-lint) | typedoc | interrogate | — |
| Config linting | — | hadolint (Docker), yamllint, shellcheck, sqlfluff, stylelint | ← same | ← same |

Multiple tools per cell are alternatives — if any one is detected, that category
is considered covered for that language. The script checks for each tool in the
cell in listed order and stops at the first hit. `missing_by_language` only
includes categories where no alternative was detected, and emits the first
(highest-value) tool in the cell as the recommendation.

---

## Section 2: `references/quality-standards.md`

Loaded by the model during audit generation to bind the code quality phase.

### Concrete thresholds

| Dimension | Warning | Error |
|---|---|---|
| Function length (excl. blanks/comments) | > 25 lines | > 50 lines |
| File length | > 300 lines | > 600 lines |
| Function parameters | > 4 | > 7 |
| Nesting depth | > 3 levels | > 5 levels |
| Cyclomatic complexity | > 10 per function | > 20 per function |
| Cognitive complexity | > 15 per function | — |
| Return points | > 3 per function | — |
| Public API doc coverage | any missing doc comment | — |

### Named code smells (model-detected)

The model samples files from the `risk_surfaces` discovered by the script and
looks for the following named patterns. Each finding is reported with file, line,
smell name, and a one-sentence explanation.

**Structural smells:**
- **God object** — one type/file owns disproportionate responsibility; ask "what does this not do?"
- **Anemic domain model** — domain types are pure data bags; all business logic lives in external manager/service/util layers
- **Middle man** — a module or type exists solely to delegate to another; provides no logic of its own
- **Refused bequest** — a subtype overrides or ignores most inherited behavior, suggesting the inheritance is wrong
- **Inappropriate intimacy** — two modules reference each other's internals bidirectionally; neither has a clean boundary

**Coupling smells:**
- **Feature envy** — a function references another module's internals more than its own
- **Message chains** — `a.b().c().d()` — callers traverse deep chains of internal structure, coupling them to implementation
- **Temporal coupling** — caller must invoke methods in a specific undocumented order; signals: unguarded `Init`/`Open`/`Start` methods, doc comments saying "must call X before Y", nil-risk reads before initialization
- **Hidden side effects** — a function that reads or queries by name but also mutates state or triggers I/O

**Data smells:**
- **Data clump** — 3+ values always passed together but never structured into a type
- **Primitive obsession** — domain concepts expressed as raw strings/ints instead of typed values
- **Stringly typed** — config, errors, or events passed as unvalidated raw strings where types would eliminate entire error classes
- **Magic values** — unexplained literals embedded in logic with no named constant or comment

**Design smells:**
- **Divergent change** — a module changes for unrelated reasons, indicating low cohesion
- **Leaky abstraction** — callers must know implementation details to use a component correctly
- **Inconsistent abstraction level** — a function mixes high-level intent with low-level implementation detail in the same body

### Design-level heuristics (qualitative)

For each unit sampled during the code quality phase, the model assesses:

- Can you explain what this unit does in one sentence without mentioning its internals?
- Can you change the internals without breaking callers?
- Does naming match the domain vocabulary, or is it generic (`Manager`, `Handler`, `Data`, `Info`)?
- Is error handling deliberate (typed errors, context added) or reflexive (`if err != nil { return err }`)?
- Are interfaces discovered (extracted from usage) or invented (speculative)?

### Severity model

All findings — from tools and from model analysis — use this scale:

| Level | Meaning |
|---|---|
| `error` | Blocks merge/release; must fix |
| `warning` | Should fix before next feature work |
| `note` | Worth addressing, not urgent |
| `skip` | Acknowledged, intentionally deferred |

---

## Section 3: `references/static-analysis-tools.md`

Loaded by the model to know which commands to emit and what to recommend.

**Per detected tool, the generated audit emits a concrete run block:**

```markdown
### golangci-lint
- Command: `golangci-lint run ./...`
- Surface: `error` findings → audit errors; `warning` findings → audit warnings
- Config: note any disabled linters or raised thresholds in `.golangci.yml`

### govulncheck
- Command: `govulncheck ./...`
- Surface: any CVE finding → audit error regardless of reported severity

### gitleaks
- Command: `gitleaks detect --source . --verbose`
- Surface: any detected secret → audit error; review false positives against `.gitleaksignore`
```

**For each missing tool, the generated audit emits a recommendations block:**

```markdown
## Recommended Static Analysis (not currently configured)

- **knip** — detects unused exports, files, and dependencies (TypeScript)
  Install: `npm install -D knip` + add `"knip": "knip"` to package.json scripts
- **bandit** — security linter for Python; no config required to start
  Install: `pip install bandit` then `bandit -r .`
```

**Model-based fallback:** When zero tools are detected, the model performs a full
quality pass using `quality-standards.md` directly — sampling files from each
`risk_surface` in the discovery output and applying all thresholds and smell
detection by reading code. This is not a footnote; it is the primary code quality
phase.

---

## Section 4: `SKILL.md` changes

### Updated discovery workflow

Add two steps after the existing six:

**Step 7 — Static analysis surface:**
Cross-reference `static_analysis.detected_tools` from the script output against
`references/static-analysis-tools.md`. Note all gaps in `missing_by_language`.
Read the config file of each detected tool and note any disabled rules, raised
thresholds, or excluded paths — these are findings in themselves if they weaken
the analysis.

**Step 8 — Quality standards binding:**
Load `references/quality-standards.md`. Note it will govern the code quality
audit phase. The sampling target is files within the discovered `risk_surfaces`
first, then highest-churn files from git log, then remainder.

### New audit modules

Add to the existing module list (include only those that fit the repo):

- **static analysis** — run all detected tools, capture output, surface findings by severity
- **dependency health** — outdated packages, unused dependencies, license compliance
- **secrets scan** — always included; scans git history and working tree
- **duplication** — cross-file clone detection
- **test coverage** — coverage gaps against risk surfaces specifically; no blanket % target
- **documentation coverage** — exported/public symbol coverage
- **code quality** — model-based review using quality-standards thresholds and smell catalog

### New generation rules

- For each detected tool: emit a concrete run block with command, output
  interpretation instructions, and severity mapping.
- For each missing tool: emit a recommendations block with install instructions.
  Do not recommend tools that conflict with existing ones (e.g. do not recommend
  ruff if flake8 is already configured).
- For the code quality phase: sample files from `risk_surfaces` first; apply all
  thresholds; call out named smells by file and line where possible.
- When zero tools detected: the model-based quality pass is the primary phase,
  not a fallback footnote.
- Coverage thresholds must not be hardcoded in generated audits — surface gaps
  in risk surfaces only, never mandate a specific % target.

### New guardrails

- Do not emit tool run blocks for tools absent from `detected_tools`.
- Secrets scan is always included; it is never optional regardless of stack.
- Do not let the recommendations block become a shopping list — recommend only
  the highest-value missing tool per gap, not every alternative.
- If a tool's config disables or weakens rules, flag it as a finding, not just
  a note.
