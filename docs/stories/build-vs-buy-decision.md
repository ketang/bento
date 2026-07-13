---
schema_version: 1
title: Build vs Buy Evaluates Before Building New Functionality
slug: build-vs-buy-decision
status: active
authority: observed
change_resistance: medium
tests_applicable: false
locked_sections:
  - Intent
---

# Build vs Buy Evaluates Before Building New Functionality

## Intent
Before an agent builds a substantial feature from scratch, build-vs-buy scans the existing repo for incumbents, researches external libraries or services, and produces a structured recommendation comparing build against buy options.

## Story
An agent is asked to add background job processing to a Go web service. Before writing any code, the build-vs-buy skill fires. It runs the discover helper with a short feature brief to collect the repo's shape, package managers, major frameworks, incumbent tools already present, deployment signals, and any policy hints. Using this base layer, the agent researches external libraries (River, Asynq, Machinery) and SaaS queue offerings (SQS, Cloud Tasks), then compares them against building a simple in-process scheduler. Each option is scored against the constraints surfaced by the helper — license, compliance, hosting posture, integration cost. The agent presents the recommendation with a clear rationale; the user confirms or redirects before any implementation begins.

## Expected Behavior
- The discover helper is run first with a short feature brief.
- Missing constraints not answerable locally are confirmed with the user.
- External options are researched and scored against repo constraints.
- A recommendation is presented before any implementation code is written.
- The skill treats the helper output as evidence, not as the final decision.

## Boundaries
- Does not implement the chosen option; it only recommends.
- Does not apply to trivial changes that do not constitute "substantial new functionality."
- Treats unknown constraints as questions, not assumptions.

## Auditable Claims
- `build-vs-buy/scripts/build-vs-buy-discover.py` accepts a `--feature` flag and emits JSON with repo shape, incumbents, and deployment signals.
- The SKILL.md states: "the default is to research build vs buy first, not to assume a build-from-scratch path."

## Evidence
### Tests
### Surface
- `skill: build-vs-buy`
### Docs
- `catalog/skills/build-vs-buy/SKILL.md`
