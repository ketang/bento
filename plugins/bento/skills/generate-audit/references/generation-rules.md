# Audit Generation Rules

## Grounding and Shape

- Generate from discovered facts, not assumptions. Prefer the repo's actual
  commands and paths over generic examples.
- Keep the generated audit concise enough to be used repeatedly. Separate
  generic audit structure from repo-specific bindings. Mark expensive or
  optional phases clearly.
- Default to critical evaluation. Keep follow-up actions concrete and
  prioritized in a separate section, distinguishing immediate fixes,
  medium-term improvements, and structural investments.
- If the repo lacks enough structure to justify a full audit skill, produce
  a lightweight audit plan instead.

## Static Analysis Output

- For each detected tool: emit a concrete run block with command, output
  interpretation, and severity mapping (see `static-analysis-tools.md`).
- For each missing tool: emit a recommendations block with install
  instructions. Recommend only the highest-value missing tool per gap, not
  every alternative. Do not recommend tools that conflict with existing ones.
- Do not emit tool run blocks for tools absent from `detected_tools`.
- If a tool's config file disables or weakens rules, flag it as a finding,
  not merely a note.

## Code Quality Phase

- Sample from `risk_surfaces` first; apply all thresholds; call out named
  smells with file and line where possible.
- When zero tools are detected, the model-based quality pass is the primary
  code quality phase, not a fallback footnote.

## Coverage and Tests

- Coverage thresholds must not be hardcoded — surface gaps in risk surfaces
  only; never mandate a specific percentage target.
- Treat disabled or bypassed automated tests as findings candidates when
  they weaken confidence.

## Documentation Findings

- Treat broken or misleading install and quickstart commands as findings
  when they block onboarding or verification.
- Treat correct-but-low-utility documentation as a documentation-quality
  problem when it wastes reader attention or omits the information needed
  to act.
- Do not mistake documentation presence for documentation quality; utility
  and correctness both matter. Do not reward docs that are merely verbose,
  obvious, or duplicative.

## Guardrails

- Do not hardcode Rust, Go, TypeScript, Beads, GitHub, or any specific tool
  unless the repo actually uses it.
- Do not copy a foreign repo's audit verbatim and swap names.
- Do not let the generated audit become a giant project SOP dump.
- Do not require issue creation, commits, or memory edits by default.
- Do not execute destructive or environment-mutating commands just because
  they appear in docs; prefer safe local verification first.

## Draft Skill Structure

When drafting a repo-local `audit` skill, structure it as:

1. Purpose and scope
2. Audit phases
3. Output format
4. Optional post-audit actions
