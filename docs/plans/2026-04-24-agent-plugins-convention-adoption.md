# agent-plugins Convention Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent-plugins convention discoverable from bento's top-level documentation so contributors and external adopters can find the spec, and so bento begins treating it as a ratified convention of this repo.

**Architecture:** Three targeted documentation edits — `README.md`, `AGENTS.md`, and `DESIGN.md` — each adding a short section or cross-reference that points to `docs/specs/2026-04-24-agent-plugins-convention-design.md`. No code, no tests, no reference implementation. A reference implementation is deferred to the `/handoff` skill, which will be the first concrete consumer of the convention and will write the lookup logic as part of its own implementation.

**Tech Stack:** Markdown only. No build-script changes, no version bumps (changes are outside `catalog/skills/` and `scripts/build-plugins`, so the version-bump rule in `AGENTS.md` does not apply).

---

## File Structure

Files to modify:

- `README.md` — add a "Conventions" section pointing to the spec.
- `AGENTS.md` — add a "Conventions" section under "Rules for agents" so agents working in this repo are aware of the convention.
- `DESIGN.md` — add a "Conventions" section under the key decisions area, explaining why bento has ratified the convention and pointing to the spec.

No new files. No changes to `catalog/`, `plugins/`, `scripts/`, `hooks/`, or `install/`.

---

### Task 1: Add Conventions section to README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the section**

Open `README.md`. After the existing `## Worktree convention` section (which currently ends with the line that starts `Use /tmp only for ephemeral scratch data...`), insert the following new section before `## Current target platforms`:

```markdown
## Agent-plugins convention

Bento follows the `agent-plugins` convention for user-editable plugin
customization files. Plugins that expose editable templates, rule lists, or
similar user-facing customization files read them from an XDG-respecting
home-scope directory and a repo-scope directory, with a defined
override precedence over plugin-bundled defaults.

The convention is cross-marketplace and agent-neutral. See
[docs/specs/2026-04-24-agent-plugins-convention-design.md](docs/specs/2026-04-24-agent-plugins-convention-design.md)
for the full specification.
```

- [ ] **Step 2: Verify the file edit**

Run: `grep -n "Agent-plugins convention" README.md`
Expected: one matching line showing the new heading.

Run: `grep -n "docs/specs/2026-04-24-agent-plugins-convention-design.md" README.md`
Expected: one matching line showing the cross-reference.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): reference agent-plugins convention"
```

---

### Task 2: Add Conventions section to AGENTS.md

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: Add the section**

Open `AGENTS.md`. After the existing `## Framing guidance` section (which ends with the bullet that begins `avoid language that implies the repo is only useful for one agent runtime...`), insert the following new section before `## Safe editing guidance`:

```markdown
## Conventions this repo follows

- `agent-plugins` convention: user-editable plugin customization files live at
  `<repo-root>/.agent-plugins/<marketplace>/<plugin>/...` (repo scope) and
  `$XDG_CONFIG_HOME/agent-plugins/<marketplace>/<plugin>/...` (home scope, with
  the XDG default of `~/.config/agent-plugins/` when unset). Repo scope
  overrides home scope, which overrides the plugin-bundled default. Lookup is
  per file. See
  [docs/specs/2026-04-24-agent-plugins-convention-design.md](docs/specs/2026-04-24-agent-plugins-convention-design.md)
  for the full specification.
  When editing a bento skill that exposes user-editable customization files,
  follow this convention; do not invent ad hoc locations.
```

- [ ] **Step 2: Verify the file edit**

Run: `grep -n "Conventions this repo follows" AGENTS.md`
Expected: one matching line showing the new heading.

Run: `grep -n "docs/specs/2026-04-24-agent-plugins-convention-design.md" AGENTS.md`
Expected: one matching line showing the cross-reference.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs(agents): reference agent-plugins convention"
```

---

### Task 3: Add Conventions section to DESIGN.md

**Files:**
- Modify: `DESIGN.md`

- [ ] **Step 1: Add the section**

Open `DESIGN.md`. After the existing `## Cross-Agent Worktree Policy` section (which ends with the paragraph beginning `Those overrides should still use a dedicated, durable, user-scoped worktree root...`), insert the following new section before `## Skill implementation pattern`:

```markdown
## Agent-Plugins Convention

Bento ratifies the `agent-plugins` convention as the location and lookup rule
for user-editable plugin customization files.

Rationale: plugins frequently expose user-editable artifacts (prompt templates,
rule lists, allow/deny lists, fill-in-the-blank content skeletons). Without a
shared convention, each plugin chooses its own location ad hoc, and a user who
installs plugins from multiple marketplaces has to learn an inconsistent
scatter of customization paths. A small, focused convention solves layout and
lookup without reaching into orthogonal concerns like cache, runtime state,
install mechanics, or packaging.

Key positions:

- Home-scope base directory honors XDG: `$XDG_CONFIG_HOME/agent-plugins/`,
  falling back to `~/.config/agent-plugins/` when unset.
- Repo-scope base directory is `<repo-root>/.agent-plugins/`.
- Path layout below each base is two-level: `<marketplace>/<plugin>/...`.
  Each plugin chooses its own internal substructure.
- File-level override precedence: repo scope beats home scope beats
  plugin-bundled default.
- Creation mechanics are deliberately unspecified. Plugins may use installers,
  session-lifecycle hooks, first-use self-healing, or manual user setup.

The convention is cross-marketplace and agent-neutral by design; bento is its
first concrete adopter but the intent is that other marketplaces can follow it
without modification. See
[docs/specs/2026-04-24-agent-plugins-convention-design.md](docs/specs/2026-04-24-agent-plugins-convention-design.md)
for the full specification.
```

- [ ] **Step 2: Verify the file edit**

Run: `grep -n "Agent-Plugins Convention" DESIGN.md`
Expected: one matching line showing the new heading.

Run: `grep -n "docs/specs/2026-04-24-agent-plugins-convention-design.md" DESIGN.md`
Expected: one matching line showing the cross-reference.

- [ ] **Step 3: Commit**

```bash
git add DESIGN.md
git commit -m "docs(design): ratify agent-plugins convention"
```

---

### Task 4: Verify repo still builds and tests pass

This task guards against a collision between the new markdown and any docs-linting or build-time checks the repo may run.

**Files:**
- No file edits.

- [ ] **Step 1: Run the build script**

Run: `scripts/build-plugins`
Expected: build completes without error; the command's built-in `python3 -m unittest discover -s tests -t .` step reports all tests passing.

If the build script fails, investigate the failure; do not mark this task complete.

- [ ] **Step 2: Verify no untracked changes slipped in**

Run: `git status`
Expected: clean working tree; no modifications to generated plugin directories or marketplace manifests triggered by the build. The plan's edits are all to documentation under the repo root and should not touch generated output.

- [ ] **Step 3: No commit needed**

This task is verification-only. If step 1 passes and step 2 shows a clean tree, the task is done.

---

## Self-Review

**Spec coverage check:** This plan publishes the convention; it does not implement the lookup logic. That deferral is explicit in the spec's "Implementation Latitude" section (mechanics are unspecified) and in this plan's goal statement (first concrete consumer is `/handoff`, not this plan). Spec sections and task coverage:

- Spec "Summary", "Motivation", "In Scope", "Out of Scope", "Non-Goals" → referenced by the new README, AGENTS.md, and DESIGN.md sections.
- Spec "Base Directories", "Path Layout", "Override Precedence" → summarized in the AGENTS.md and DESIGN.md additions.
- Spec "Lookup Algorithm", "Implementation Latitude", "Compatibility with Existing Conventions", "Future Extensions", "Conformance" → reachable via the cross-reference to the spec file; not summarized in the doc additions (the pointer is sufficient; restating risks drift).

**Placeholder scan:** No TBDs, TODOs, or vague "handle appropriately" steps. Every task has exact file paths, exact content to insert, and exact commands with expected output.

**Type consistency:** Not applicable; no code changes.

**No test failures were created by this plan** because there is no code to test. The verification task runs the existing build and test suite to confirm the documentation edits do not regress anything upstream of them.

---

## Notes for the implementer

- All three doc-edit tasks are independent. They can be executed in any order. The plan presents them in the order README → AGENTS → DESIGN because that matches the order a new reader would typically encounter them when onboarding to the repo.
- The commit messages use bento's existing convention (`docs(<area>): <summary>`). Do not add co-author trailers unless the repo's established commit style requires them.
- After Task 4 passes, the adoption work is complete. The next unit of work is the `/handoff` skill, which will be brainstormed, specced, planned, and implemented separately and will be the first concrete consumer of the convention.
