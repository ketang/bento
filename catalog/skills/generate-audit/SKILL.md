---
name: generate-audit
description: |
  Use when a repo needs a project-specific audit playbook or local `audit`
  skill. Discovers the repo's stack, gates, docs, interfaces, and risk
  surfaces, then generates a concise audit procedure tailored to that repo.
recommended_model: high
---

# Generate Audit

## Model Guidance

Recommended model: high.

Use a high-capability model for autonomous execution. This skill is a
meta-skill that requires broad repo inference and tailored output shaping.

Use this skill to create a repo-specific audit plan, or to draft a local
`audit` skill for the current project.

This is a meta-skill. It does not run the full audit by default. It generates
the audit procedure that a repo should use.

## Deterministic Helper

This skill includes `generate-audit/scripts/audit-discover.py` to collect a
deterministic base layer of repo facts before the model starts shaping the
audit. Invoke this helper by script path, not `python3 <script>`, so approvals
stay scoped to the script.

Run it first:

```bash
generate-audit/scripts/audit-discover.py
```

Use the JSON output as the starting point for:

- project shape and detected languages
- build, test, lint, and typecheck command candidates
- source-of-truth docs and workflow docs
- documentation buckets, documented command candidates, and command-consistency signals
- interface and drift surfaces
- workflow surfaces such as CI, task runners, tracker hints, and memory files
- disabled or bypassed automated-test signals across code, CI, config, and docs
- path-based risk hotspots worth deeper review

Then fill in only the gaps that the helper cannot infer from file structure
alone.

## Output Modes

Choose one of these outputs based on the user's request:

- audit plan: a markdown checklist or procedure for a one-off audit
- draft skill: a repo-local `audit` skill ready for refinement
- both: first the audit plan, then a draft skill built from the same findings

## Discovery Workflow

1. Run the helper and use its output as the deterministic base layer.
2. Identify the project shape:
   - primary languages and frameworks
   - package/workspace layout
   - build, test, lint, and typecheck commands
   - CI scripts, Make targets, or task runners
3. Identify the project's source-of-truth docs:
   - README
   - contributor instructions
   - architecture or product docs
   - API, protocol, schema, or migration docs
   - agent-oriented instructions such as `AGENTS.md`
   - install, setup, and quickstart docs that claim a user can accomplish real work
4. Critically review documentation, not just its existence:
   - design and architecture docs for correctness, omissions, drift, and weak assumptions
   - in-code and code-adjacent docs for stale contracts, misleading comments, and undocumented constraints
   - agent-facing docs for whether they drive high-quality behavior or merely restate obvious mechanics
   - all docs for utility: flag content that is correct but irrelevant, obvious, redundant, or too shallow to help a contributor, operator, or agent succeed
5. Identify interface and drift surfaces:
   - API schemas
   - protocol types
   - generated code
   - config and env var contracts
   - CLI commands and flags
6. Identify workflow surfaces:
   - issue tracker or task system
   - branch and merge conventions
   - release or closeout scripts
   - memory or knowledge files if the repo uses them
7. Perform a dedicated critical review of automated test health:
   - inspect `test_automation_health.disabled_signals` from the helper output
   - look for disabled, skipped, quarantined, muted, or bypassed tests in code, CI, task runners, and docs
   - treat these as findings candidates when they reduce confidence, leave coverage gaps, or normalize broken test workflows
   - explain what risk each disabled path leaves untested
8. Identify risk-heavy areas:
   - auth and permissions
   - routers and input validation
   - persistence and migrations
   - external network calls
   - background jobs
   - secrets and token handling
9. Validate documentation truthfulness with command checks:
   - inspect `documentation_analysis.commands` and `documentation_analysis.command_consistency`
   - prioritize install, setup, quickstart, run, build, and test commands
   - execute documented commands when they are safe, local, and relevant to the audit
   - treat failing, drifting, misleading, or prerequisite-free assumptions as findings, not just notes
   - report whether docs help a real contributor or operator accomplish work, or merely describe the obvious
10. Static analysis surface — read `generate-audit/references/static-analysis-tools.md`:
   - Cross-reference `static_analysis.detected_tools` from the helper output
   - Note all gaps from `missing_by_language` and `missing_cross_language`
   - Read the config file of each detected tool and note any disabled rules,
     raised thresholds, or excluded paths — these are findings if they weaken
     the analysis
11. Quality standards binding — read `generate-audit/references/quality-standards.md`:
   - This governs the code quality audit phase
   - Sampling target: files in `risk_surfaces` first, then highest-churn files
     from `git log --format='' --name-only | sort | uniq -c | sort -rn | head -20`,
     then remainder

## Audit Modules

Include only the modules that fit the discovered repo. The usual set is:

- build health
- static analysis (run detected tools; emit run blocks per `static-analysis-tools.md`)
- code quality (model-based review using thresholds and smell catalog from `quality-standards.md`)
- dependency health (outdated packages, unused dependencies, license compliance)
- secrets scan (always include; scans git history and working tree)
- contract or schema consistency
- duplication (cross-file clone detection)
- test coverage (gap analysis against risk surfaces; no blanket % target)
- documentation coverage (exported/public symbol coverage)
- docs truthfulness
- documentation utility
- issue hygiene
- foundation review
- security review
- usability and ergonomics
- regression sampling
- session or process retrospective

Omit modules that do not match the repo. Do not invent a frontend UX section
for a backend-only service, or a migration section for a repo with no database.

**Always include:** secrets scan — it is never optional regardless of stack.

## Generation Rules

- Generate from discovered facts, not assumptions.
- Prefer the repo's actual commands and paths over generic examples.
- Keep the generated audit concise enough to be used repeatedly.
- Separate generic audit structure from repo-specific bindings.
- Mark expensive or optional phases clearly.
- Default to critical evaluation. Follow-up actions should be concrete and prioritized in a separate section.
- For each detected tool: emit a concrete run block with command, output
  interpretation instructions, and severity mapping (see `static-analysis-tools.md`).
- For each missing tool: emit a recommendations block with install instructions.
  Do not recommend tools that conflict with existing ones.
- For the code quality phase: sample files from `risk_surfaces` first; apply
  all thresholds; call out named smells by name with file and line where possible.
- When zero tools detected: the model-based quality pass is the primary code
  quality phase, not a fallback footnote.
- Coverage thresholds must not be hardcoded — surface gaps in risk surfaces only;
  never mandate a specific percentage target.
- Treat disabled or bypassed automated tests as explicit findings candidates when they weaken confidence.
- Treat broken or misleading install and quickstart commands as findings, especially when they block onboarding or verification.
- Treat correct-but-low-utility documentation as a documentation-quality problem when it wastes reader attention or omits the information needed to act.
- Prefer remediation guidance that distinguishes immediate fixes, medium-term improvements, and structural investments.

When drafting a repo-local `audit` skill, structure it as:

1. purpose and scope
2. audit phases
3. output format
4. optional post-audit actions

## Guardrails

- Do not hardcode Rust, Go, TypeScript, Beads, GitHub, or any specific tool
  unless the repo actually uses it.
- Do not emit tool run blocks for tools absent from `detected_tools`.
- Do not require issue creation, commits, or memory edits by default.
- Do not copy a foreign repo's audit verbatim and swap names.
- Do not let the generated audit become a giant project SOP dump.
- Do not let the recommendations block become a shopping list — recommend only
  the highest-value missing tool per gap, not every alternative.
- If the repo lacks enough structure to justify a full audit skill, produce a
  lightweight audit plan instead.
- Secrets scan is always included; it is never optional regardless of stack.
- If a tool's config file disables or weakens rules, flag it as a finding, not
  merely a note.
- Do not mistake documentation presence for documentation quality; utility and correctness both matter.
- Do not reward docs that are merely verbose, obvious, or duplicative.
- Do not execute destructive or environment-mutating commands just because they appear in docs; prefer safe local verification first.

## Recommended Output Shape

The generated plan or skill should usually include:

- an executive summary section
- phase-by-phase checks with concrete commands or files
- a severity model for findings
- concrete remediation guidance tied to the findings
- a final consolidated action list

For a draft skill, keep the first version lean. It is better to generate a
useful 6-phase audit that matches the repo than a bloated 10-phase audit full
of guesses.
