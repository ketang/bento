---
name: maintain-web-demo
description: Use when an existing webapp demo or walkthrough may be stale after changes to user-facing flows, routes, selectors, accessible names, seed data, auth/session setup, app startup, containers, functional Playwright tests, screenshot artifacts, warning queues, or `make demo`-style commands. Updates the existing demo against the `generate-web-demo` contract rather than creating a parallel harness.
---

# Maintain Web Demo

## Overview

Keep existing webapp demo/walkthroughs synchronized with the product and test
suite. Treat the current demo as an executable spec with visible and headless
runs, not as disposable presentation code.

## Workflow

1. Find the demo command, runner, screenshots, warning queue, and options file.
2. Read the nearby product code, routes, tests, seed data, and startup scripts
   touched by the current change.
3. Compare the existing walkthrough against the `generate-web-demo` contract:
   same scenario for visible/headless runs, named steps, assertions,
   screenshots, deterministic startup, artifacts, and warning queue emission.
4. Update only the drifted pieces: selectors, accessible names, routes, seed
   data, assertions, screenshots, artifact paths, warning messages, or command
   wiring.
5. Keep functional tests and walkthrough helpers aligned. Share login, seed,
   navigation, and selector helpers where the repo already supports that.
6. Run the demo headless for verification. Run visible only when needed to
   inspect timing, controller behavior, or human-observable flow.
7. Preserve warning/failure screenshots for review. Do not hide demo failures
   by deleting assertions.

## Drift Checks

Check for these recurring causes of stale demos:

- route or navigation changes
- changed button labels, headings, ARIA labels, roles, or test IDs
- auth/session or seed data changes
- altered app startup, port, environment, or container topology
- functional tests that now cover a different flow than the walkthrough
- warning queue schema changes
- screenshot artifact layout changes
- visible controller changes that accidentally affect screenshots

## Warning-Queue Contract Migration

Demos installed before the queue-matching lifecycle was defined often carry an
outdated `AGENTS.md` contract that tells agents to match queued failures only
against open or in-progress issues. That contract re-files duplicates when a
closed bug regresses. When maintaining such a demo, update the installed
contract to match the warning-queue tracker lifecycle in
`references/generate-web-demo-contract.md`:

- match queued failures by failure identity (step id + signature), not title
- search ALL issues, open and closed
- reopen a matching closed issue on recurrence instead of filing a new one
- require a pasted passing run over the affected step ids before closing

Look for stale contract phrasing such as "existing open or in-progress bug" and
replace it with the reopen-on-recurrence and pasted-passing-run rules.

## References

Read `references/generate-web-demo-contract.md` for the expected contract
established by the companion skill.
