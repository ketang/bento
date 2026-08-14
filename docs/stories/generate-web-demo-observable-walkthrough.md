---
schema_version: 1
title: Generate Web Demo Creates an Observable Browser Walkthrough
slug: generate-web-demo-observable-walkthrough
status: active
authority: observed
change_resistance: medium
tests_applicable: false
locked_sections:
  - Intent
---

# Generate Web Demo Creates an Observable Browser Walkthrough

## Intent
When a webapp needs a human-observable walkthrough, generate-web-demo produces a Playwright scenario with visible and headless execution paths, step screenshots, deterministic startup, and a warning queue — all from a single canonical scenario.

## Story
A team wants to show a new onboarding flow to stakeholders and also have agents generate improvement ideas from it. They invoke generate-web-demo. The skill inspects the repo for existing Playwright conventions, app startup commands, seed data, and service dependencies. It builds one canonical scenario with named steps covering the golden path, adds assertion checks at meaningful boundaries, and captures screenshots at each step including warning and failure states. A `make demo` target is wired up so both visible and headless runs use the same steps, with headless as the default when no visibility flag is passed and `--headed`/`--visible` opting into the watchable run; the visible path also mounts the controller overlay so a viewer can pause, resume, step, and stop. The resulting demo serves both audiences: a stakeholder watches the visible run; an agent reviews screenshots and the warning queue to generate improvement proposals. The demo resets data deterministically so it can be re-run at any time.

## Expected Behavior
- A single canonical scenario drives both visible and headless execution paths.
- Screenshots are taken at every meaningful step, including warning and failure states.
- Assertions are placed at meaningful boundaries, not just screenshots.
- App and dependency startup is deterministic and containerized when needed.
- A project-native entry point (usually `make demo`) is created.
- Headless is the default mode when no visibility flag is provided; the runner accepts `--headed`/`--visible`.
- A stable artifact directory holds screenshots, logs, metadata, and the warning queue.
- A warning queue captures non-fatal issues for later agent attention, emitted on every run unless disabled by options.
- The visible run mounts a controller overlay supporting pause, resume, step, and stop.
- Maintenance notes tie the walkthrough to overlapping functional tests.

## Boundaries
- Does not create a parallel harness if the repo already has an equivalent browser automation stack.
- Does not hide demo failures by deleting assertions.

## Auditable Claims
- The SKILL.md "Required Contract" enumerates eleven required demo components, including the canonical scenario, visible/headless paths, assertions, screenshots, deterministic data and startup, a project-native entry point, a stable artifact directory, warning-queue emission, the visible-run controller overlay, and maintenance notes tying the demo to overlapping functional tests.
- The warning queue is a documented required output artifact, designed per `generate-web-demo/references/warning-queue.md`.
- The visible-run controller ships as `generate-web-demo/assets/playwright-controller/controller.js`.
- Both visible and headless runs must use the same steps — documented as a hard requirement.

## Evidence
### Tests
### Docs
- `catalog/skills/generate-web-demo/SKILL.md`
- `catalog/skills/generate-web-demo/references/warning-queue.md`
- `catalog/skills/generate-web-demo/assets/playwright-controller/controller.js`
