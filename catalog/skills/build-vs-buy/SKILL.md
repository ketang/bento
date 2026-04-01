---
name: build-vs-buy
description: |
  Use before building substantial new functionality. Runs a deterministic repo
  scan to surface incumbent tools and constraints, then researches libraries or
  services and compares them against a build baseline before implementation.
---

# Build vs Buy

Use this skill before building a substantial feature, component, integration,
or subsystem. The default is to research build vs buy first, not to assume a
build-from-scratch path.

## Deterministic Helper

This skill includes `scripts/build-vs-buy-discover.py` to collect a
repo-specific base layer before the model starts external research.

Run it first with a short feature brief:

```bash
python3 scripts/build-vs-buy-discover.py --feature "add background jobs"
```

Use the JSON output as the starting point for:

- repo shape, package managers, and major frameworks
- incumbent tools already present in relevant capability categories
- deployment, hosting, and cloud signals detectable from local files
- policy hints, stack preferences, and open questions that need confirmation
- integration surfaces and migration touchpoints that affect adoption cost

Treat helper output as evidence, not as the decision itself. If a constraint is
reported as unknown, ask instead of guessing.

## Workflow

1. Run the helper with a short feature brief.
2. Confirm any missing constraints that the repo cannot answer locally:
   - hosting and SaaS posture
   - license or procurement limits
   - compliance or data-handling requirements
   - whether new services must stay within an existing cloud footprint
3. Research viable open-source libraries or hosted services that fit the repo's
   detected stack and constraints.
4. Narrow to the best candidates and always include a `build` baseline.
5. Present a comparison that includes:
   - fit with the existing stack
   - implementation time
   - operational burden
   - integration and migration cost
   - lock-in, license, and cost risks
   - category-specific concerns surfaced by the helper
6. Ask which option to pursue before implementation begins.

## Skip Conditions

Skip this workflow only when one of these is already true:

- the user explicitly says to build from scratch
- the user explicitly names the dependency or service to adopt
- repo policy or existing architecture docs mandate one option

## Guardrails

- Do not recommend introducing a second tool in a category that already has an
  incumbent without explaining why the current stack is insufficient.
- Do not let generic ecosystem popularity override repo-local constraints.
- Do not treat missing evidence as permission.
- Do not omit the `build` baseline from the comparison.
