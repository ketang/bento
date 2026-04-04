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

### Step 5 — Act on the classification

**If behavioral or mixed:**

1. Run `scripts/bump-plugin-versions` and capture its JSON output.
2. If bumps were applied, run `scripts/build-plugins` to regenerate artifacts.
3. Commit the version bump and regenerated files together:
   ```
   git add catalog/plugin-versions.json plugins/ .claude-plugin/marketplace.json .agents/plugins/marketplace.json
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
- Default to patch bumps. Do not attempt to infer semver level from the diff.
- Push policy is independent — pushes remain eager and frequent regardless of
  whether a version bump occurred.
