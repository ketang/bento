---
schema_version: 1
title: Code Bloat Sniffer Reports Removal Candidates
slug: code-bloat-sniffer-removal-candidates
status: draft
authority: observed
change_resistance: low
locked_sections: []
---

# Code Bloat Sniffer Reports Removal Candidates

## Intent
A maintainer seeking to shrink a codebase receives an evidence-backed report of removal candidates.

## Story
The skill inventories the target, excludes generated and dependency directories, analyzes chunks in parallel except for trivial targets, and confirms cross-chunk duplication by inspecting bodies. It consolidates findings into one Markdown report sorted by confidence and payoff.

## Expected Behavior
Every finding includes a location, negative-search evidence, blast radius, and a proposed verification step; findings missing any of these are dropped. Low-confidence findings appear only when the requested focus widens the net.

## Boundaries
The skill recommends verification commands but does not run tests, edit source, remove dependencies, or file tracker issues.

## Auditable Claims
- The skill requires all four pieces of evidence for each finding.
- The skill writes one Markdown report and does not edit source or file issues.

## Evidence

### Docs
- `catalog/skills/code-bloat-sniffer/SKILL.md`
