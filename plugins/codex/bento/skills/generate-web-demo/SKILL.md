---
name: generate-web-demo
description: "Use when a webapp needs a human-observable demo or walkthrough generated with browser automation, especially Playwright: create visible and headless runs from the same scenario, step screenshots, deterministic app/server/database startup, a project-native target such as `make demo`, a visible-run controller, artifacts for review or Bugshot, and a warning/error queue for later agent attention."
---

# Generate Web Demo

## Overview

Create a browser-driven webapp demo/walkthrough that acts as a
human-observable executable spec. Default to Playwright unless the repository
already has an equivalent browser automation stack with visible/headless runs,
assertions, and screenshot capture.

There are two use cases, not two scenario modes:

- A human operator reviews the current app state and screenshots to generate
  improvement ideas.
- A human shows another human what the software does.

Keep the scenario, assertions, screenshots, warning queue, and artifacts the
same for both use cases. The meaningful runtime difference is whether the
browser is visible or headless.

## Discovery

Before designing the demo, inspect the repository for:

- existing Playwright, browser-test, or screenshot conventions
- app startup commands, ports, auth/session setup, and seed data
- database, queue, object store, and other service dependencies
- container commands such as Docker Compose or project-specific dev scripts
- Make, npm/pnpm/yarn, just, or task targets for test/build/demo
- existing screenshots, Bugshot baselines, and warning queues
- functional tests covering the same flows

Prefer the repo's existing test helpers, fixtures, selectors, and startup
scripts over inventing a parallel harness.

## Required Contract

Generate or update the demo so it has:

- one canonical scenario with named steps
- visible and headless execution paths using the same steps
- assertion checks at meaningful boundaries, not only screenshots
- screenshots for every meaningful step, including warning/failure states
- deterministic data setup and reset
- deterministic app and dependency startup, including containers when needed
- a project-native entry point, usually `make demo`
- a stable artifact directory containing screenshots, logs, metadata, and the
  warning queue
- warning/error queue emission on every run unless disabled by options
- a visible-run controller overlay for pause, resume, step, and stop
- maintenance notes that tie the walkthrough to overlapping functional tests

Use Playwright fixtures or helper modules to keep the scenario readable. Name
steps for humans; avoid filenames like `step-1.png` when a descriptive slug is
available.

## Implementation Workflow

1. Discover the existing app/test/startup conventions.
2. Draft the scenario as a sequence of user-observable product outcomes.
3. Add deterministic startup and seed/reset handling before browser actions.
4. Add a runner that accepts at least `--headed`/`--visible` and headless
   operation. Headless must be the default mode when no visibility flag is
   provided. The two paths must execute the same scenario.
5. Add step wrappers that assert, capture screenshots, and append warning
   records without stopping warn-only runs.
6. Add the visible controller from
   `assets/playwright-controller/controller.js` when the browser is visible.
7. Add a project-native command such as `make demo`; include container startup
   there when that is how the app normally runs.
8. Run the demo headless as verification. If feasible, run visible once or
   explain why it was not run.
9. Document the artifact directory, options file, and expected warning queue
   handling in the repo's existing contributor or agent docs.

If the repo already has a demo, preserve its public command and artifact paths
unless changing them materially improves consistency.

## References

- Read `references/options-file.md` when adding user-editable demo settings.
- Read `references/warning-queue.md` when designing warning/error emission.
- Read `references/artifacts.md` when choosing output directories and file
  names.
- Read `references/maintenance.md` when documenting how future agents keep the
  demo synchronized with tests and product changes.
- Copy or adapt `assets/playwright-controller/controller.js` for visible
  Playwright runs.
