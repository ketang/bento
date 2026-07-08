# Audit Report Rules

## Grounding and Shape

- Audit from discovered facts, not assumptions. Prefer the repo's actual
  commands and paths over generic examples.
- Keep the report concise enough to act on. Separate deterministic facts,
  model judgment, and human preferences. Mark expensive, skipped, or optional
  checks clearly.
- Default to critical evaluation. Keep follow-up actions concrete and
  prioritized in a separate section, distinguishing immediate fixes,
  medium-term improvements, and structural investments.
- If the repo lacks enough structure for a full audit, produce a lightweight
  report with explicit gaps and recommended next checks.

## Static Analysis Output

Discovery emits two adjacent fields:

- `applicable_tools` — language fit + (when required) config-file fit. The
  tool *would be appropriate* for this repo.
- `installed_tools` — the subset of `applicable_tools` whose binary is on
  `PATH` (verified via `shutil.which`). The tool *can actually run* in this
  environment.

Rules:

- For each entry in `installed_tools`: emit a concrete run block with
  command, output interpretation, and severity mapping (see
  `static-analysis-tools.md`).
- For each entry in `applicable_tools` that is **not** in `installed_tools`:
  emit a recommendation block with install instructions. The tool fits the
  repo but is not installed, so it cannot run as part of this audit. Treat
  this exactly like the `missing_by_language` recommendation path; do not
  emit a run block claiming the tool ran.
- For each entry in `missing_by_language` and `missing_cross_language`: emit
  a recommendation block. Recommend only the highest-value missing tool per
  gap, not every alternative. Do not recommend tools that conflict with
  existing ones.
- Never emit a run block for a tool absent from `installed_tools`. A clean
  audit must reflect tools that actually executed, not tools that *could*
  have executed in a differently-provisioned environment.
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
- When `demo_walkthrough_signals` is non-empty, include demo/walkthrough drift
  as a warning-level audit module. Check run commands, visible/headless parity,
  screenshots, warning queues, and overlap with functional tests. Recommend
  `maintain-web-demo` for drifted demos and `generate-web-demo` for webapps
  with important human-observable workflows but no demo.

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
- Do not let the report become a giant project SOP dump.
- Do not require issue creation, commits, or memory edits by default.
- Do not execute destructive or environment-mutating commands just because
  they appear in docs; prefer safe local verification first.
- Do not generate a repo-local `audit` skill unless the user explicitly asks
  for legacy generation output.

## Optional Legacy Draft Skill Structure

When the user explicitly asks for a repo-local `audit` skill, structure that
legacy draft as:

1. Purpose and scope
2. Audit phases
3. Output format
4. Optional post-audit actions
