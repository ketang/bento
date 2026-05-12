---
name: generate-audit
description: Use when a repo needs a project-specific audit playbook or local `audit` skill tailored to its stack and risk surfaces.
recommended_model: high
---

# Generate Audit

## Model Guidance

Recommended model: high — this is a meta-skill requiring broad repo inference
and tailored output shaping.

Use this skill to create a repo-specific audit plan, or to draft a local
`audit` skill for the current project. This is a meta-skill: it does not run
the full audit by default. It generates the audit procedure that a repo should
use.

## Deterministic Helper

`generate-audit/scripts/audit-discover.py` collects a deterministic base layer
of repo facts (project shape, build/test/lint/typecheck commands, source-of-
truth docs, interface and drift surfaces, workflow surfaces, disabled-test
signals, risk hotspots, static-analysis tool detection, documentation command
consistency) before the model shapes the audit. Invoke by script path so
approvals stay scoped.

```bash
generate-audit/scripts/audit-discover.py
```

Use the JSON output as the starting point, then fill gaps using
`generate-audit/references/discovery-checklist.md`.

## Output Modes

- **audit plan** — a markdown checklist or procedure for a one-off audit
- **draft skill** — a repo-local `audit` skill ready for refinement
- **both** — first the audit plan, then a draft skill from the same findings

## Workflow

1. Run the helper; use its JSON as the deterministic base layer.
2. Work through `generate-audit/references/discovery-checklist.md` to fill in
   project shape, docs review, interfaces, workflow surfaces, test health,
   risk areas, documentation truthfulness, static analysis, and quality
   standards — skip surfaces that do not apply.
3. Select audit modules from the list below.
4. Generate the output in the requested mode, following
   `generate-audit/references/generation-rules.md`.

## Audit Modules

Include only modules that fit the discovered repo:

- build health (for Go repos where `static_analysis.language_signals.Go.concurrency_signals`
  is non-empty, run `go test -race -timeout 120s ./...` in place of plain `go test ./...` —
  any race finding is `error`-level, and missing `-race` in repo CI is `warning`-level
  whenever the codebase has goroutines)
- static analysis (run detected tools; emit run blocks per `static-analysis-tools.md`;
  fold semgrep results under both "static analysis" and "security review" for
  polyglot repos — its rules span both surfaces)
- code quality (model-based review using thresholds and smell catalog from `quality-standards.md`)
- dependency health (outdated packages, unused dependencies, license compliance)
- **secrets scan** (always include; scans git history and working tree)
- contract or schema consistency
- duplication (cross-file clone detection)
- test coverage (gap analysis against risk surfaces; no blanket % target)
- test strategy diversity (unit / property-based / golden-file / fuzz —
  surface absence in repos where the pattern fits, e.g. golden-file harness
  for input→output transformation tools, property-based tests for
  parser/serializer/transform packages with crisp invariants)
- mutation testing (Go only; **gated** — apply only to packages with line
  coverage ≥ 80% AND classified as risk surface; below threshold emit
  "mutation testing premature; raise coverage first"; above threshold run
  `gremlins unleash` and report surviving mutants per package, not a
  percentage; each surviving mutant in a risk-surface function → `warning`;
  run this module after test-coverage gap module)
- documentation coverage (exported/public symbol coverage)
- documentation hygiene (automated) — run markdownlint, lychee, and typos
  on any repo with `*.md` files; distinct from the model-based
  "documentation utility" pass; markdownlint/typos finding → `warning`;
  broken link → `error`
- docs truthfulness
- demo/walkthrough drift (warning-level by default; include when the repo has
  browser demos, walkthrough scripts, `make demo`-style commands, screenshot
  artifact conventions, `.demo-warnings.jsonl`, or Bugshot-linked demo output;
  escalate only when the repo makes the demo part of a required gate)
- documentation utility
- issue hygiene
- foundation review
- security review
- usability and ergonomics
- regression sampling
- session or process retrospective

Omit modules that do not match the repo. Do not invent a frontend UX section
for a backend-only service, or a migration section for a repo with no
database. **Secrets scan is never optional.** When recommending CI for a
repo with no `.github/workflows/`, include `actionlint` in the proposed
setup so new workflows are linted from day one.

## Output Shape

The generated plan or skill should include: executive summary, phase-by-phase
checks with concrete commands or files, severity model for findings, concrete
remediation guidance tied to findings, and a final consolidated action list.
For a draft skill, keep the first version lean — a useful 6-phase audit that
matches the repo beats a bloated 10-phase audit full of guesses.

See `generate-audit/references/generation-rules.md` for grounding, static-
analysis output format, code-quality sampling, coverage handling,
documentation-finding rules, guardrails, and the draft-skill structure.
