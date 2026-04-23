---
name: static-analysis-tools
description: Per-tool run commands, output interpretation, and recommendation guidance for the static analysis audit phase
---

# Static Analysis Tools

This reference is loaded during audit generation to govern the **static
analysis** audit phase. For each tool in `static_analysis.detected_tools`,
emit a concrete run block using the template below. For tools in
`missing_by_language` and `missing_cross_language`, emit a recommendations block.

## Run Block Template

For each detected tool, emit:

```markdown
### <tool-name>
- **Command:** `<run command from detected_tools entry>`
- **Config:** `<config file>` — note any disabled rules, raised thresholds, or
  excluded paths; these are findings if they weaken the analysis
- **Surface:** <interpretation guidance below>
```

## Per-Tool Interpretation Guidance

### golangci-lint
Surface all `error`-level findings as audit errors. Surface `warning`-level as
audit warnings. Note the active linter set from `.golangci.yml`; a sparse set
(e.g. only `errcheck` enabled) is itself a `warning`-level finding.
Run: `golangci-lint run ./...`

### govulncheck
Any CVE finding → audit `error` regardless of reported severity. Zero findings
is a clean pass.
Run: `govulncheck ./...`

### gofmt
Any output (unformatted files listed) → audit `warning` per file.
Run: `gofmt -l .`

### go-test-cover
Report coverage % per package from the func output. Flag packages in
`risk_surfaces` with coverage below 60% as `warning`; below 30% as `error`.
Do not mandate a repo-wide coverage target.
Run: `go test -coverprofile=coverage.out ./... && go tool cover -func=coverage.out`

### deadcode
Any unreachable function → audit `warning`. Exported-but-unreachable in a
library → `note` (may be public API).
Run: `deadcode ./...`

### gocyclo
Functions with cyclomatic complexity > 10 → audit `warning`. Complexity > 20
→ audit `error`. These thresholds match the code quality phase benchmarks in
`quality-standards.md`. Report each function with its score; do not average.
Run: `gocyclo -over 10 ./...`

### dupl
Any clone above the threshold → audit `note`. Review before flagging — some
duplication (e.g. test fixtures) is intentional.
Run: `dupl ./...`

### nancy
Any vulnerable dependency → audit `error`. Run after `go list -json -deps ./...`.
Run: `go list -json -deps ./... | nancy sleuth`

### eslint
`error`-level findings → audit errors. `warning`-level → audit warnings. Note
any disabled rules in config; widespread `// eslint-disable` comments are a
`warning`-level finding in themselves.
Run: `npx eslint . --format=compact`

### tsc
Any type error → audit `error`. `strict: false` in `tsconfig.json` → audit
`warning`.
Run: `npx tsc --noEmit`

### knip
Unused exports → audit `warning`. Unused dependencies → audit `note`. Review
false positives for dynamic imports before reporting.
Run: `npx knip`

### prettier
Any file failing the check → audit `warning` per file.
Run: `npx prettier --check .`

### jscpd
Any clone above the threshold → audit `note`. Review before flagging.
Run: `npx jscpd .`

### ruff
`E` and `F` category findings → audit `warning`. Security (`S`) findings →
audit `error`. Note any `ignore` directives in config.
Run: `ruff check .`

### mypy
Any type error → audit `error`. `ignore_errors = true` or broad `# type: ignore`
usage → audit `warning`.
Run: `mypy .`

### bandit
`HIGH` severity findings → audit `error`. `MEDIUM` → audit `warning`. Review
false positives (e.g. MD5 for non-security hashing) before escalating.
Run: `bandit -r .`

### pytest-cov
Flag risk-surface modules with coverage below 60% as `warning`, below 30% as
`error`. No repo-wide target.
Run: `pytest --cov`

### interrogate
Coverage below 80% → audit `warning`. Below 50% → audit `error`.
Run: `interrogate .`

### vulture
Any dead code hit in non-test files → audit `note`. Confirm before reporting —
vulture has false positives on dynamically accessed attributes.
Run: `vulture .`

### radon
Grade the cyclomatic complexity of each function. Grade B (CC 6–10) → audit
`note`. Grade C–D (CC 11–20) → audit `warning`. Grade E–F (CC > 20) → audit
`error`. These thresholds match the code quality phase benchmarks in
`quality-standards.md`. Report each function with its score and grade; do not
average across the module.
Run: `radon cc . --min B -s`

### clippy
Any `deny`-level finding → audit `error`. `warn`-level → audit `warning`. Note
`#[allow(...)]` attributes that suppress important lints. `clippy::cognitive_complexity`
is in the `nursery` group and is **off by default** — check for it separately via
the `clippy-cognitive-complexity` entry below.
Run: `cargo clippy -- -D warnings`

### clippy-cognitive-complexity
Detected when `clippy.toml` or `.clippy.toml` is present (the threshold must be
configured there — the default of 25 is too permissive to catch real-world
complexity). Functions exceeding the configured threshold → audit `warning`.
Check that `clippy.toml` sets `cognitive-complexity-threshold` to a value ≤ 15;
if the file exists but omits the key, flag that as a `note` (threshold defaults
to 25). If the config file is absent entirely, this entry appears in the
recommendations block — see below.
Run: `cargo clippy -- -W clippy::cognitive_complexity`

### cargo-audit
Any CVE → audit `error`. Unmaintained crates → audit `warning`.
Run: `cargo audit`

### rustfmt
Any file failing check → audit `warning`.
Run: `cargo fmt --check`

### cargo-tarpaulin
Flag risk-surface modules with coverage below 60% as `warning`, below 30% as
`error`. No repo-wide target.
Run: `cargo tarpaulin`

### gitleaks
Any detected secret → audit `error`. Review `.gitleaksignore` entries; overly
broad suppression patterns are a `warning`.
Run: `gitleaks detect --source . --verbose`

### trufflehog
Any high-confidence finding → audit `error`. Medium-confidence → `warning`.
Run: `trufflehog filesystem .`

### detect-secrets
Any finding not in the baseline → audit `error`. A stale baseline (last updated
>6 months ago) → audit `warning`.
Run: `detect-secrets scan .`

### hadolint
`DL` and `SC` findings at `error` level → audit errors. `warning` → audit
warnings.
Run: `hadolint Dockerfile`

### yamllint
Any syntax or formatting error → audit `warning`.
Run: `yamllint .`

### shellcheck
Any `error` or `warning` finding → audit `warning`. Focus on files in `scripts/`
and CI workflow scripts first.
Run: `find . -name '*.sh' -not -path './.git/*' | xargs shellcheck`

## Recommendations Block Template

For each tool in `missing_by_language` and `missing_cross_language`, emit one
entry. Recommend only the highest-value missing tool per gap — do not list every
alternative.

```markdown
## Recommended Static Analysis (not currently configured)

- **<tool>** — <one-line description of what it catches>
  Install: `<install command>`
  First run: `<run command>`
```

### clippy-cognitive-complexity recommendation text

When `clippy-cognitive-complexity` appears in `missing_by_language` for Rust,
emit:

```markdown
- **clippy cognitive_complexity** — catches functions with high cognitive
  complexity; requires opt-in because the default threshold (25) is too
  permissive to be useful without configuration.
  Setup: create `clippy.toml` with `cognitive-complexity-threshold = 15`
  Enable: `cargo clippy -- -W clippy::cognitive_complexity`
```

### Do not recommend
- A tool that conflicts with an already-configured alternative (e.g. do not
  recommend `ruff` if `flake8` is already configured)
- More than one tool per gap — pick the canonical recommendation from the tool
  detection map

## Model-Based Fallback

When `static_analysis.detected_tools` is empty, perform a full model-based
quality pass using `quality-standards.md` as the primary code quality phase —
not a fallback footnote. Sample from `risk_surfaces`, apply all thresholds, and
name smells by the catalog.
