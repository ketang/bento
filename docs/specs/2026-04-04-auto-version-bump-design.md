# Design: Automatic Version Bump Skill

**Date:** 2026-04-04
**Status:** Approved

## Goal

Give the agent autonomous judgment over when to bump plugin versions in the
bento repo, so the human never has to remember or decide. Pushes remain eager
and frequent for safety; version bumps happen only when enough meaningful
behavioral work has accumulated.

---

## Architecture

Two files are added:

| File | Purpose |
|---|---|
| `.claude/skills/version-bump.md` | Repo-local skill encapsulating the bump heuristic and workflow |
| `AGENTS.md` (modify) | Policy line instructing the agent to invoke the skill at natural completion points |

No changes to `bump-plugin-versions` or `build-plugins` — the skill orchestrates
them as-is.

---

## Skill Workflow

1. **Check for canonical changes** — identify the last version bump commit
   (`git log -n1 --format=%H -- catalog/plugin-versions.json`) and check whether
   any canonical sources changed since then
   (`git diff --name-only <commit> -- catalog/skills/ scripts/build-plugins`).
   If nothing changed, stop.

2. **Read the diffs** — `git diff <last-version-commit>..HEAD -- catalog/skills/ scripts/build-plugins`
   to get the accumulated changes.

3. **Judge behavioral vs cosmetic** — apply the judgment criteria below to the
   diff. Classify the accumulated changes as behavioral, cosmetic, or mixed.

4. **If behavioral or mixed** — run `scripts/bump-plugin-versions`, then
   `scripts/build-plugins`, then commit the version bump and regenerated files.

5. **If cosmetic only** — skip. Work continues to accumulate until the next
   evaluation.

## Judgment Criteria

The skill instructs the model to classify the diff using these categories:

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

## AGENTS.md Policy

Add to `AGENTS.md`:

```
## Version Management

After completing a meaningful unit of work (feature complete, all plan tasks
done, or ending a session with unbumped behavioral changes in catalog/skills/),
invoke the `.claude/skills/version-bump.md` skill to evaluate whether a version
bump is warranted. Do not bump manually — the skill handles the judgment.

Pushes are independent of version bumps. Push eagerly and frequently for safety.
```

## Idempotency

- If `bump-plugin-versions` reports no bumps needed (no canonical changes since
  last version commit), the skill does nothing.
- If the skill was already invoked and bumped for the current set of changes,
  invoking it again is a no-op.
- Running `build-plugins` after a bump is always safe — it regenerates
  deterministically.

## What This Does NOT Change

- Push frequency or policy — pushes remain eager
- The `bump-plugin-versions` script itself — reused as-is
- The `build-plugins` script — reused as-is
- The `land-work` skill — remains general-purpose, unmodified
- Version bump semantics (patch/minor/major) — defaults to patch; the skill
  does not attempt to infer semver level from the diff
