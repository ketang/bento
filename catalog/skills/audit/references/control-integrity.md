# Control Integrity

Guidance for three modules that ask whether controls actually bind, rather than
what code does when everything is configured: configuration failure mode, gate
integrity, and agent-instruction integrity.

The shared question is: what happens when a value, tool, or file is **absent**?
A control that degrades to permissive on absence is a finding even when every
configured path is correct.

## Configuration Failure Mode

Build a table over every config key and env var the code reads. Sources:
`interface_surfaces` config/env entries from discovery, plus a direct read of
settings/env loaders, `.env.example`, chart/compose files, and CI env blocks.

One row per key: name, where read, default when absent or empty, and the
resulting behavior. Then classify each row `fail-closed`, `fail-open`, or
`inert`.

`error` when absence or emptiness produces any of:

- a permissive mode selected by inference rather than explicit opt-in — no
  secret and no identity provider configured, so the service boots a dev/test
  auth mode instead of refusing to start
- an empty allowlist treated as allow-all rather than deny-all (tool
  allowlists, CORS origins, admin lists, IP ranges)
- a missing optional privacy or locality backend that silently falls through
  to a less-private default — no local model configured, so content goes to a
  cloud provider
- an absent verification or scan tool that makes its gate skip rather than fail
- an unset bound that means "unlimited" where the safe reading is "reject" —
  no token expiry meaning never-expires, no size cap meaning unbounded upload

`warning` when absence degrades functionality without weakening a security,
privacy, or correctness boundary.

Report the row, the exact file and line of the defaulting expression, and the
safe alternative (refuse to start, deny-all, or explicit opt-in flag). Do not
mutate the environment to test this — read the defaulting code.

## Gate Integrity

Run the repo's own documented gate commands on a clean checkout. Use
`documentation_analysis.command_consistency` for the documented set and
`project_shape.commands` for what exists. Run only safe local commands; never
deploy, release, migration, or production-data targets.

For each gate, record the command, exit status, and whether the reported
outcome matches what the docs claim it enforces.

- Standard gate already red on the primary branch → `error`. A gate nobody can
  pass is not a gate; note how long it has been red if git history shows it.
- A gate that skips silently when its tool is absent → `error`. Look for
  `command -v tool || exit 0`, `which tool >/dev/null || echo skip`, and
  `continue-on-error` in CI. Verify by checking the recipe, not only by the
  exit code on this machine.
- A threshold documented as required but enforced nowhere → `error`. Report the
  doc/enforcement mismatch as the finding, and include the current actual value
  so the size of the gap is visible.
- Documented gate behavior the recipe does not perform — a `full`/`e2e` target
  that runs no e2e, a `lint` target that lints one of five packages → `warning`.

Distinguish three outcomes explicitly in the report: **failed** (ran, red),
**skipped** (did not run, reported success), and **advisory** (ran, red, not
enforced). Silent skip and advisory-despite-documented-requirement are the
findings this module exists to catch; a plain failure is often already known.

## Agent-Instruction Integrity

Cheap; include for any repo containing agent config (`CLAUDE.md`, `AGENTS.md`,
`GEMINI.md`, `.claude/`, `.agents/`, `.cursor/`).

Resolve every `@import` and referenced rules path transitively from each agent
doc, following imports inside imported files until the graph closes. For each
resolved path:

- missing file, or a file that resolves to zero bytes → `error`. A rules file
  that exists but is empty carries no instructions; treat it exactly like a
  dangling import.
- a path that should be a directory but is a 0-byte file or an unpopulated
  submodule pointer → `error`. A removed submodule leaves the whole rules tree
  inert while every import still looks satisfied.
- an import cycle or a path escaping the repo → `warning`.

Then check registered hooks in `.claude/settings.json`, `.claude/settings.local.json`,
and equivalent runtime config: the command exists and is executable → absent
command is `error`. A wrapper that gates on an external binary and exits 0 when
that binary is missing is a silent no-op → `warning`, escalating to `error`
when the hook is the enforcement point for a documented rule.

Report the count of inert instruction bytes, not just the file list: "nine
imported rules files, all resolving to the same 0-byte path" is the finding,
not nine separate ones.

Bento's `agent-env-doctor` SessionStart hook performs these checks live at
session start. The overlap is intentional: the hook is the always-on layer for
repos that have it installed, this module is the periodic sweep that also
covers repos that do not. Do not skip the module because the hook exists; do
note in the finding when the hook was installed and did not catch the problem,
since that is a hook defect worth routing separately.

## Degradation

These modules must run model-driven when deterministic collectors are absent.
Where discovery supplies `documentation_analysis.command_consistency`,
`interface_surfaces`, or `static_analysis.installed_tools`, use it as the base
layer; where it does not, read the config loaders, gate recipes, and agent docs
directly and say in the report which parts were model-derived.
