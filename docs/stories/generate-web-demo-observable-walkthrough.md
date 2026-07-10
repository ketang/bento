---
schema_version: 1
title: Generate Web Demo Creates an Observable Browser Walkthrough
slug: generate-web-demo-observable-walkthrough
status: active
authority: observed
change_resistance: medium
tests_applicable: true
locked_sections:
  - Intent
---

# Generate Web Demo Creates an Observable Browser Walkthrough

## Intent
When a webapp needs a human-observable walkthrough, generate-web-demo produces a Playwright scenario with visible and headless execution paths, step screenshots, deterministic startup, and a warning queue — all from a single canonical scenario.

## Story
A team wants to show a new onboarding flow to stakeholders and also have agents generate improvement ideas from it. They invoke generate-web-demo. The skill inspects the repo for existing Playwright conventions, app startup commands, seed data, and service dependencies. It builds one canonical scenario with named steps covering the golden path, adds assertion checks at meaningful boundaries, and captures screenshots at each step including warning and failure states. A `make demo` target is wired up so both visible and headless runs use the same steps. The resulting demo serves both audiences: a stakeholder watches the visible run; an agent reviews screenshots and the warning queue to generate improvement proposals. The demo resets data deterministically so it can be re-run at any time.

## Expected Behavior
- A single canonical scenario drives both visible and headless execution paths.
- Screenshots are taken at every meaningful step, including warning and failure states.
- Assertions are placed at meaningful boundaries, not just screenshots.
- App and dependency startup is deterministic and containerized when needed.
- A project-native entry point (usually `make demo`) is created.
- A warning queue captures non-fatal issues for later agent attention.

## Boundaries
- Does not create a parallel harness if the repo already has an equivalent browser automation stack.
- Does not hide demo failures by deleting assertions.
- Does not substitute for functional test coverage.

## Auditable Claims
- The SKILL.md "Required Contract" documents the seven required demo components: scenario, visible/headless paths, assertions, screenshots, deterministic data, deterministic startup, and project-native entry point.
- The warning queue is a documented required output artifact.
- Both visible and headless runs must use the same steps — documented as a hard requirement.

## Evidence
### Tests
### Surface
- `skill: generate-web-demo`
- `cli: make demo`
### Docs
- `catalog/skills/generate-web-demo/SKILL.md`
