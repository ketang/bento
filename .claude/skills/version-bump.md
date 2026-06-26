---
name: version-bump
description: |
  Evaluate whether plugin versions should be bumped based on accumulated
  canonical changes since the last version commit. Classifies changes as
  behavioral or cosmetic and only bumps when behavioral work has accumulated.
---

# Version Bump

## When to Use

Invoke this skill at natural completion points: feature complete, all plan
tasks done, or ending a session with unbumped behavioral changes in
`catalog/skills/` or `scripts/build-plugins`.

## Workflow

### User-requested bumps

If the user explicitly asks to bump versions, skip the helper decision step.
Bump the requested plugin(s), or all plugins if unspecified, using the semver
part the user requested. If no part is specified, use the semver part selection
rules below, defaulting to patch only when no higher-level rule applies. Then
run `scripts/build-plugins`.

### Step 1 — Find the baseline

Identify the last version bump commit:

```
git log -n1 --format=%H -- catalog/plugin-versions.json
```

If no commit exists, stop — the version file needs manual bootstrapping.

### Step 2 — Check for canonical changes

List files changed since the baseline:

```
git diff --name-only <baseline> -- catalog/skills/ scripts/build-plugins
```

If nothing changed, stop. No bump needed.

### Step 3 — Read the diffs

Get the accumulated diff for classification:

```
git diff <baseline>..HEAD -- catalog/skills/ scripts/build-plugins
```

### Step 4 — Classify the changes

Apply these judgment criteria to the diff:

**Behavioral (bump):**
- New, removed, or renamed files in `catalog/skills/`
- Changed logic in Python scripts (new functions, modified control flow, new
  data structures, changed detection maps)
- New or modified reference documents that change what the model does during
  audit generation
- Changed SKILL.md frontmatter (name, description, recommended_model)
- New or modified audit modules, generation rules, guardrails, or discovery
  workflow steps
- New or modified test assertions (indicates changed expected behavior)

**Cosmetic (skip):**
- Whitespace-only changes
- Line wrapping or reformatting without semantic change
- Comment rewording or typo fixes
- Reordering items in a list without adding or removing entries
- Changes to docs/, specs, plans, or non-catalog files

**Mixed (bump):**
- A diff that contains both behavioral and cosmetic changes is treated as
  behavioral. Err on the side of bumping.

### Step 5 — Choose the semver part

Apply these rules after deciding a bump is required:

**Patch:**
- Behavioral changes that do not intentionally change the user-facing contract
  of a plugin or skill
- Bug fixes in helper scripts
- Clarified or corrected workflow guidance that preserves intent
- New or modified tests for existing behavior
- Packaging changes that preserve compatibility

**Minor:**
- Backward-compatible additions of user-visible capability
- Adding a new skill to an existing plugin, unless the same change includes a
  compatibility break
- New optional workflow paths, commands, hook points, customization files, or
  generated output fields
- Expanded support for another runtime, tracker, framework, or repo convention

**Major:**
- Intentional compatibility breaks or significant contract changes
- Removing or renaming skills, hooks, commands, customization paths, manifest
  fields, generated artifacts, required inputs, expected outputs, or lifecycle
  order
- Changing lookup precedence or canonical source locations in a way existing
  users must adapt to
- Removing support for a runtime or previously supported convention

If multiple rules match, use the highest applicable semver part. When the level
is unclear, default to patch and call out the uncertainty in the final summary
or commit message.

### Step 6 — Act on the classification

**If behavioral or mixed:**

1. Run `scripts/bump-plugin-versions --part <patch|minor|major>` and capture
   its JSON output.
2. If bumps were applied, run `scripts/build-plugins` to regenerate artifacts.
3. Commit the version bump and regenerated files together:
   ```
   git add catalog/plugin-versions.json plugins/ .claude-plugin/marketplace.json
   git commit -m "chore: bump plugin versions for <brief description of changes>"
   ```

**If cosmetic only:**

Skip. Work continues to accumulate until the next evaluation.

## Idempotency

- If `bump-plugin-versions` reports no bumps needed (empty `bumps` in its JSON
  output), do nothing further.
- If this skill was already invoked and bumped for the current set of changes,
  invoking it again is a no-op.
- Running `build-plugins` after a bump is always safe — it regenerates
  deterministically.

## Constraints

- Do not modify `scripts/bump-plugin-versions` or `scripts/build-plugins`.
- Default to patch only when no minor or major rule applies.
- Push policy is independent — pushes remain eager and frequent regardless of
  whether a version bump occurred.
