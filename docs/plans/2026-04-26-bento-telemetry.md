# Bento Telemetry And Bentobug Epic Plan

**Date:** 2026-04-26

## Confirmed Decisions

- Telemetry is internal bento observability for bento helper scripts.
- `bento-telemetry` is not a user-facing skill or plugin.
- `bentobug` is user-facing, but it is independent from telemetry.
- Telemetry may enrich `bentobug` reports when available, but `bentobug`
  must work without telemetry installed, enabled, or populated.
- Telemetry support must work from installed plugin artifacts. It must not rely
  on repo-root `scripts/bento-telemetry` paths.
- Implementation issues should produce code or generated artifacts. Packaging
  and storage design decisions are settled here, not deferred to a design-only
  issue.
- Version updates must use repo tooling. Do not hand-edit
  `catalog/plugin-versions.json`.

## High-Level Architecture

Telemetry has three internal pieces:

1. A Python stdlib library for schema construction, classification, redaction,
   attribution, storage paths, and append-only JSONL writes.
2. A `PostToolUse(Bash)` hook that records outcomes for bento-owned helper
   scripts and always exits `0`.
3. An internal CLI for maintainers and bento internals: `path`, `tail`,
   `summarize`, and an `export` stub reserved for future opt-in shipping.

Bentobug is a separate user-facing reporting surface:

1. A `bentobug` skill or command captures a user report with a non-empty note.
2. The report target is independent of telemetry. The first implementation
   should choose one concrete storage/filing target and test it.
3. A later issue may attach recent telemetry context on a best-effort basis.

## Epic A: Internal Bento Telemetry

### Issue A1: Add Telemetry Event Library And JSONL Store

**Goal:** Create the canonical telemetry library used by the hook and internal
CLI.

**Scope:**

- Create the telemetry library under the canonical source tree.
- Define versioned `script` event records.
- Implement:
  - `classify`
  - `redact_stderr`
  - script attribution
  - record builders
  - UTC JSONL path selection
  - append-only record writes
- Enforce non-world-readable telemetry directories and files.
- Add focused unit tests.

**Behavioral requirements:**

- `ok`: exit code `0` and not interrupted.
- `not_found`: exit code `126` or `127` plus stderr indicating missing command,
  missing file, or permission denied.
- `error`: any other nonzero exit, or any interrupted run. Interrupted runs are
  `error` even if the exit code is `0`.
- Redact `$HOME` to `~`.
- Redact `/tmp/claude-session-<id>/` paths to `<scratch>/`.
- Store only stderr tail: last 20 lines and at most 4 KiB.
- Do not capture stdout.

**Tests:**

- Classification covers `0`, `126`, `127`, `1`, and interrupted runs.
- Redaction covers home paths, session scratch paths, line limits, and byte
  limits.
- Attribution covers:
  - real generated bento cache layout
  - development layout under `catalog/skills/<skill>/scripts/<file>`
  - unrelated commands
- Append tests verify JSONL shape and restrictive file permissions.

**Acceptance:**

- Library tests pass.
- The library can build a valid `script` event for a realistic generated bento
  helper path.
- Unrelated paths return no record.

### Issue A2: Add Robust Bash Hook Recorder

**Goal:** Record bento helper-script Bash outcomes from Claude
`PostToolUse(Bash)` hook events without affecting the session.

**Scope:**

- Add a `PostToolUse(Bash)` hook script.
- Parse hook input defensively.
- Extract the actual candidate script path from common command forms.
- Realpath candidate scripts when possible.
- Build and append telemetry records through the library.
- Log hook-internal failures separately from telemetry data.
- Always exit `0`.

**Invocation forms to support in v1:**

- Direct script path:
  - `<script> ...`
- Repo-required command prefix:
  - `rtk <script> ...`
  - `rtk proxy <script> ...`
- Interpreter-wrapped helper:
  - `python3 <script> ...`
  - `python <script> ...`
  - `bash <script> ...`

Shell pipelines, command substitutions, and complex chains may be best-effort
in v1, but the parser must not throw.

**Tests:**

- Records successful direct helper invocation.
- Records runtime error.
- Records interrupted run as `error`.
- Records missing watched script as `not_found` where hook payload contains
  matching exit/stderr.
- Records `rtk <script>` invocation.
- Records `python3 <script>` invocation.
- Ignores unrelated commands.
- Malformed payload exits `0` and does not write telemetry.
- Hook-internal exceptions are captured in the hook error log without raising.

**Acceptance:**

- Hook tests pass.
- The hook does not break the session for bad input, unknown commands, or
  telemetry write failures.

### Issue A3: Add Internal Telemetry CLI

**Goal:** Provide a local support CLI for maintainers and bento internals.

**Scope:**

- Add an internal executable with subcommands:
  - `path`
  - `tail`
  - `summarize`
  - `export`
- `export` is a stub that exits `2` with a clear "not implemented" message.
- The CLI must import/use the canonical telemetry library from its packaged
  installed location, not only from the development checkout.

**Command behavior:**

- `path`: prints the telemetry JSONL directory.
- `tail [-n N] [--skill X] [--session ID|current]`: prints newest matching
  records as compact JSONL.
- `summarize [--since 7d] [--skill X] [--plugin Y] [--class C]
  [--session ID|current] [--json]`: aggregates script records per
  `(skill, script)`.
- `export`: reserved for future opt-in shipping.

**Tests:**

- `tail` orders by event timestamp, not only file iteration order.
- `tail` skips corrupt JSONL lines.
- `summarize` aggregates across multiple days.
- `summarize` filters by `--since`, `--skill`, `--plugin`, `--class`, and
  `--session`.
- `--json` output has stable keys.
- Timezone-aware ISO timestamps parse correctly.
- `export` returns exit code `2`.

**Acceptance:**

- CLI tests pass.
- The CLI works against an empty store.
- The CLI works against seeded multi-day telemetry files.

### Issue A4: Package Telemetry Support Into Generated `bento`

**Goal:** Make telemetry work from installed bento plugin artifacts.

**Scope:**

- Include telemetry hook and support scripts in the generated `bento` plugin.
- Preserve existing `bento` hooks:
  - `auto-allow.py`
  - `seed-agent-plugins.py`
- If `scripts/build-plugins` only supports one hook catalog per plugin, extend
  it to compose multiple hook sources or otherwise package telemetry alongside
  existing bento hooks.
- Ensure generated paths are what hook JSON and internal CLI invocations expect.
- Do not rely on repo-root `scripts/bento-telemetry` for installed use.

**Tests:**

- Generated `plugins/claude/bento/hooks/hooks.json` contains existing bento
  hooks and telemetry hook entries.
- Generated `plugins/claude/bento/hooks/scripts/` contains existing hook scripts
  and telemetry support scripts.
- Generated `plugins/claude/bento` contains a runnable telemetry CLI/support
  executable at the path used by bento internals.
- Existing build-plugin tests for Claude and Codex materialization still pass.
- Codex behavior is explicit:
  - either telemetry hook artifacts are Claude-only because the hook runtime is
    Claude-specific,
  - or Codex support is intentionally implemented and tested.

**Acceptance:**

- `scripts/build-plugins` produces installed artifacts that contain all
  telemetry runtime dependencies.
- Existing bento hook functionality remains packaged.

### Issue A5: Telemetry Build, Version, And Verification

**Goal:** Regenerate artifacts and bump versions through repo tooling.

**Scope:**

- Run relevant unit tests.
- Run `scripts/bump-plugin-versions`.
- Run `scripts/build-plugins`.
- Commit generated plugin artifacts and marketplace manifests.

**Acceptance:**

- Do not manually replace `catalog/plugin-versions.json`.
- Generated plugin manifests contain the bumped versions.
- `.claude-plugin/marketplace.json` is regenerated.
- `.agents/plugins/marketplace.json` is regenerated if the build currently
  produces it.
- Full test suite passes, or any skipped/unavailable external validation is
  documented.

## Epic B: Bentobug

### Issue B1: Add Independent `bentobug` Skill

**Goal:** Provide a user-facing way to report bento bugs without depending on
telemetry.

**Scope:**

- Create `catalog/skills/bentobug/SKILL.md`.
- Define when the skill should and should not trigger.
- Require a non-empty user note.
- Infer the target skill/plugin when obvious.
- Ask one concise disambiguation question when the target is unclear.
- Choose one concrete initial report target before implementation:
  - local JSONL reports under XDG state,
  - Beads issue,
  - GitHub issue,
  - or another repository-approved target.

**Non-goals:**

- Do not require telemetry.
- Do not infer the report target only from telemetry events.
- Do not make `bentobug` a wrapper around the telemetry CLI.

**Tests / Verification:**

- Generated skill appears in the intended plugin artifact.
- Trigger and counter-trigger wording is reviewed against normal bento skill
  directives so bare skill mentions do not over-trigger.

**Acceptance:**

- Users have a clear `/bentobug` capture workflow.
- The workflow is valid when telemetry has no data.

### Issue B2: Add Bentobug Report Writer

**Goal:** Back `bentobug` with structured report creation.

**Scope:**

- Implement the script/CLI used by the skill.
- Write or file a structured report to the chosen target from B1.
- Include fields appropriate to the target, such as:
  - report id or tracker id
  - timestamp
  - note
  - reported skill/plugin if known
  - cwd
  - branch/worktree when available
  - optional recent command context if available without privacy risk
- Print a stable confirmation for the user.

**Tests:**

- Explicit target skill.
- Inferred target skill.
- Ambiguous target.
- Empty note rejected.
- Successful write/file returns a stable id or link.

**Acceptance:**

- `bentobug` can create a useful report without telemetry.
- The report writer has automated tests.

### Issue B3: Optionally Enrich Bentobug With Telemetry Context

**Goal:** Attach telemetry context to reports only when it is available and
useful.

**Scope:**

- Best-effort read from the telemetry store.
- Attach recent telemetry event ids or short summaries to the report.
- Proceed normally if telemetry is absent, disabled, empty, corrupt, or from a
  different session.
- Avoid attaching excessive or unrelated context.

**Tests:**

- Telemetry present: report includes selected recent context.
- Telemetry absent: report still succeeds.
- Telemetry corrupt: report still succeeds.
- Multiple recent skills: either choose the explicit target or ask before
  attaching ambiguous context.

**Acceptance:**

- Telemetry improves `bentobug` reports when present.
- Telemetry is never a hard dependency for reporting.

### Issue B4: Bentobug Build, Version, And Verification

**Goal:** Regenerate bentobug artifacts and bump versions through repo tooling.

**Scope:**

- Run relevant skill/report-writer tests.
- Run `scripts/bump-plugin-versions`.
- Run `scripts/build-plugins`.
- Commit generated plugin artifacts and marketplace manifests.

**Acceptance:**

- No manual version replacement.
- Generated artifacts include `bentobug`.
- Full test suite passes, or unavailable external validation is documented.

## Required Edits To The Original Draft

Remove these assumptions:

- `bento-telemetry` as a standalone public skill/plugin.
- `bentobug` as a telemetry `user_report` writer.
- `bentobug` wrapping the telemetry CLI.
- `bentobug` inferring its target only from telemetry events.
- Repo-root-only telemetry CLI usage.
- Manual `catalog/plugin-versions.json` replacement.
- Hardcoded generated/cache versions in verification commands.

Replace them with:

- Telemetry bundled as internal support for installed `bento` artifacts.
- `bentobug` as independent report capture.
- Optional telemetry enrichment as a separate follow-up.
- `rtk`-aware hook parsing and tests.
- `interrupted`-aware classification.
- Installed-artifact packaging tests.
- Version bumps through `scripts/bump-plugin-versions`.

## Final Verification Checklist

- All new commands in implementation issues should be shown with the required
  `rtk` prefix where applicable.
- Work happens in a dedicated linked worktree on a feature branch.
- Tests are added before behavioral implementation where feasible.
- Generated plugin artifacts are rebuilt with `scripts/build-plugins`.
- Version bump evaluation follows `.claude/skills/version-bump.md`.
- Final summaries call out test coverage added or explicitly state why no
  automated coverage changed.
