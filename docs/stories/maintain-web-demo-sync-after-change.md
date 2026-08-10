---
schema_version: 1
title: Maintain Web Demo Syncs Demo After Product Changes
slug: maintain-web-demo-sync-after-change
status: active
authority: observed
change_resistance: medium
tests_applicable: false
locked_sections:
  - Intent
---

# Maintain Web Demo Syncs Demo After Product Changes

## Intent
When product changes make an existing webapp demo stale, maintain-web-demo updates only the drifted pieces — selectors, routes, seed data, assertions — without creating a parallel harness.

## Story
A developer renames a button from "Submit" to "Save changes" and updates the route from `/submit` to `/confirm`. The existing Playwright demo breaks silently: the selector is wrong and the route no longer resolves. The user invokes maintain-web-demo. The skill finds the demo command, runner, screenshots, warning queue, and options file. It reads the product code, routes, and functional tests touched by the change, then compares the existing walkthrough against the generate-web-demo contract. It updates only the affected selector and route reference in the demo — nothing else. It runs the demo headless to verify the fix, confirms screenshots are updated for the renamed button's visible state, and preserves the warning and failure screenshots for review rather than deleting assertions to hide the failure. Because this demo's installed contract still matches queued failures only against open or in-progress issues, the skill also migrates it to the current warning-queue tracker lifecycle: match by failure identity rather than title, search closed issues too, reopen a matching closed issue on recurrence instead of filing a duplicate, and require a pasted passing run over the affected step ids before closing.

## Expected Behavior
- Only drifted pieces are updated; the scenario structure is preserved.
- The skill finds the existing demo rather than creating a parallel harness.
- Headless verification runs before the skill reports completion.
- Warning and failure screenshots are preserved, not deleted to hide failures.
- Functional tests and demo helpers are kept aligned when the repo supports sharing.
- A stale warning-queue tracker contract in the project's installed docs is migrated to the current lifecycle: identity-based matching, searching closed issues, reopening on recurrence, and requiring a pasted passing run before closing.

## Boundaries
- Does not create a new demo from scratch — that is generate-web-demo's job.
- Does not apply when there is no existing demo to maintain.
- Does not hide demo failures by removing assertions.
- Visible runs are used only when needed to inspect timing or human-observable flow.

## Auditable Claims
- The SKILL.md states: "Update only the drifted pieces" — scope is explicitly bounded.
- The SKILL.md states: "Do not hide demo failures by deleting assertions."
- The SKILL.md workflow states: "Run the demo headless for verification. Run visible only when needed to inspect timing, controller behavior, or human-observable flow."
- The SKILL.md "Warning-Queue Contract Migration" section requires migrating installed contracts that still match queued failures only against an "existing open or in-progress bug".

## Evidence
### Tests
### Surface
- `skill: maintain-web-demo`
- `cli: make demo`
### Docs
- `catalog/skills/maintain-web-demo/SKILL.md`
- `catalog/skills/maintain-web-demo/references/generate-web-demo-contract.md`
