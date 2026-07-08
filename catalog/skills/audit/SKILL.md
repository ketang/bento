---
name: audit
description: Use when a project needs a direct software quality audit: run discovery, inspect relevant risk surfaces, and produce a report-first assessment of correctness, maintainability, tests, docs, workflow, security, and product fit.
---

# Audit

## Model Guidance

Recommended model: high - this skill requires broad repo inference, critical
judgment, and careful synthesis across code, tests, docs, and workflow.

Use this skill to audit a project directly. The default output is a durable
audit report with structured findings and a prioritized action list. Do not
generate a project-specific audit skill by default, and do not create tracker
issues unless the user approves that follow-up after reading the report.

## Deterministic Helper

`audit/scripts/audit-discover.py` collects a deterministic base layer of repo
facts before the model starts judging quality:

- project shape, package managers, and build/test/lint/typecheck commands
- source-of-truth docs and documented command consistency
- interface, schema, config, workflow, and demo surfaces
- disabled-test signals, risk hotspots, and static-analysis tool detection
- documentation command consistency and quality-review inputs

Invoke by script path so approvals stay scoped.

```bash
audit/scripts/audit-discover.py
```

Use the JSON output as the starting point, then fill gaps using
`audit/references/discovery-checklist.md`.

## Optional Audit Profile

Current facts must be re-derived on every run. Optional profile files may only
store human decisions, persistent scope pins, accepted exclusions, report
routing preferences, and known expensive checks that require approval.

Look for profile files through the agent-plugins convention:

- repo scope: `<repo-root>/.agent-plugins/bento/bento/audit/profile.md`
- home scope: `$XDG_CONFIG_HOME/agent-plugins/bento/bento/audit/profile.md`
  with the XDG default of `~/.config/agent-plugins/bento/bento/audit/profile.md`

Repo scope overrides home scope per file. Do not create or update a profile
unless the user explicitly asks for it. Never write discovered facts such as
commands, installed tools, file inventories, git state, or test results into a
profile.

## Workflow

1. Establish scope. If the user did not narrow the request, audit the current
   repo for software quality, correctness, maintainability, tests, docs,
   security, workflow health, and user-facing/product fit where applicable.
2. Run `audit/scripts/audit-discover.py`; treat its JSON as the factual base
   layer, not as the whole audit.
3. Load the optional audit profile if present. Apply only human decisions and
   routing preferences, then continue deriving current repo facts from the
   checkout.
4. Work through `audit/references/discovery-checklist.md` to fill the helper's
   gaps. Read `audit/references/static-analysis-tools.md` and
   `audit/references/quality-standards.md` before static-analysis and code
   quality phases.
5. Select audit modules from the list below. Include only modules that match
   the discovered repo; secrets scanning is never optional.
6. Run safe local verification commands when they are relevant and available.
   Record exact commands and outcomes. Do not run destructive,
   environment-mutating, deploy, release, payment, email, migration, or
   production-data commands just because docs mention them.
7. Use specialized skills when they clearly fit and are available in the
   runtime. Examples: `code-bloat-sniffer` for removal candidates,
   `compress-docs` for agent-doc token footprint, story audit or coverage
   skills when `docs/stories/INDEX.md` exists, Shatter or Refute skills when
   configured, and web-demo maintenance skills when demo/walkthrough surfaces
   exist. Keep the final report unified.
8. Produce the report. Findings must be evidence-backed, prioritized, and
   actionable. Route meta findings to the right surface: code, tests, docs,
   tracker, process, skill, plugin, CI, or repo governance.
9. If the user wants tracker issues afterward, draft issues from the accepted
   findings only. Before filing or creating each issue, run the repo's issue
   readiness workflow, including `issue-readiness-check` when available.

## Audit Modules

Include only modules that fit the discovered repo:

- build health (for Go repos where
  `static_analysis.language_signals.Go.concurrency_signals` is non-empty, run
  `go test -race -timeout 120s ./...` in place of plain `go test ./...` - any
  race finding is `error`-level, and missing `-race` in repo CI is
  `warning`-level whenever the codebase has goroutines)
- static analysis (run detected tools; emit run blocks per
  `static-analysis-tools.md`; fold semgrep results under both "static analysis"
  and "security review" for polyglot repos - its rules span both surfaces)
- code quality (model-based review using thresholds and smell catalog from
  `quality-standards.md`)
- dependency health (outdated packages, unused dependencies, license
  compliance)
- **secrets scan** (always include; scans git history and working tree)
- contract or schema consistency
- duplication (cross-file clone detection)
- test coverage (gap analysis against risk surfaces; no blanket percentage
  target)
- test strategy diversity (unit / property-based / golden-file / fuzz -
  surface absence in repos where the pattern fits, e.g. golden-file harness for
  input-to-output transformation tools, property-based tests for
  parser/serializer/transform packages with crisp invariants)
- mutation testing (Go only; **gated** - apply only to packages with line
  coverage >= 80% AND classified as risk surface; below threshold emit
  "mutation testing premature; raise coverage first"; above threshold run the
  configured mutation-testing command and report surviving mutants per package,
  not a percentage; each surviving mutant in a risk-surface function is
  `warning`; run this module after test-coverage gap module)
- documentation coverage (exported/public symbol coverage)
- documentation hygiene (automated) - run markdownlint, lychee, and typos on
  any repo with `*.md` files; distinct from the model-based "documentation
  utility" pass; markdownlint/typos finding is `warning`; broken link is
  `error`
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
for a backend-only service, or a migration section for a repo with no database.
Secrets scan is never optional. When recommending CI for a repo with no
`.github/workflows/`, include `actionlint` in the proposed setup so new
workflows are linted from day one.

## Report Shape

Write a concise report, not a transcript. Use this structure unless the user
requested a different format:

1. Scope and evidence: repo, branch/commit, helper run, commands run, skipped
   checks with reasons.
2. Executive summary: top risks and whether the project is safe to extend,
   release, or hand to another agent.
3. Findings by severity. Each finding includes:
   - ID and title
   - severity: `error`, `warning`, `note`, or `skip`
   - surface: code, tests, docs, build, security, UX, process, tracker, skill,
     plugin, CI, or governance
   - evidence: file paths with lines where possible, command output summary,
     or exact doc claim
   - impact: why it matters for this project
   - recommendation: concrete next action
   - follow-up target: code change, test, doc, config, tracker issue, or
     profile decision
4. Clean passes: important checks that ran and did not produce findings.
5. Prioritized action list: immediate fixes, next-cycle work, and structural
   investments.

Findings must be concrete enough for a fresh agent to start work without hidden
session context. If evidence is weak, say what would confirm or refute it
instead of inflating severity.

## Guardrails

- Prefer discovered commands and repo instructions over generic examples.
- Separate deterministic facts, model judgment, and human preferences.
- Do not let profile data override current tool results or file contents.
- Do not file issues, edit memory, commit, or rewrite project policy as part of
  the audit unless the user explicitly asks.
- Do not reward documentation for existing; judge whether it helps a real
  contributor, operator, user, or coding agent succeed.
- Do not bury systemic causes. If a finding points to a bad workflow, missing
  guardrail, or skill/plugin defect, route that meta finding separately from the
  immediate code symptom.

See `audit/references/generation-rules.md` for grounding, static-analysis
output format, code-quality sampling, coverage handling, documentation-finding
rules, and report guardrails.
