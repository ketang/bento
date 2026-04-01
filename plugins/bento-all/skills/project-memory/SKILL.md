---
name: project-memory
description: |
  Use when a repo maintains durable knowledge files for future sessions.
  Captures factual and procedural knowledge, logs deterministic and
  infrastructure errors appropriately, and keeps the repo's documented memory
  structure clean over time.
---

# Project Memory

Use this skill when a repo stores durable knowledge in markdown or similar text
files and expects that knowledge to persist across sessions.

## Discovery

Before writing anything, identify the repo's documented memory structure:

- where durable knowledge lives
- whether the repo distinguishes domain facts from procedures
- whether there is a dedicated error log
- which files act as indexes, routing pages, or category summaries

Do not assume every repo uses the same folder names or file names. If the repo
does not document a durable knowledge structure, do not invent one without user
or repo-level approval.

## Knowledge Model

Track two kinds of knowledge:

- Domain knowledge: what things are
- Procedural knowledge: how to do things

When the repo already separates these, preserve that separation. A common
pattern is a hierarchy such as:

- `knowledge/INDEX.md` routes to categories
- category files hold the detailed facts
- read top-down and load only what you need

Treat that layout as an example, not a requirement.

## Error Logging

Log errors in the repo's dedicated error log, if it has one.

- Deterministic errors: conclude immediately and capture the lesson
- Infrastructure errors: log the event first and wait for a pattern before
  concluding root cause

If the repo does not separate transient error logs from durable knowledge, keep
the distinction explicit in the content rather than silently mixing the two.

Move stable conclusions out of the error log and into the appropriate domain,
procedural, or routing file.

## Maintenance

- Review relevant knowledge files at session start when the repo expects that
  workflow
- Merge overlapping categories
- Split files that grow too large
- Remove stale knowledge
- Add new categories when patterns emerge
- Propose updates to project instructions when repeated lessons should become
  rules

## Guardrails

- Do not assume `knowledge/INDEX.md` exists.
- Do not assume `ERRORS.md` exists.
- Do not create a new memory tree just because one would be convenient.
- Do not treat speculative conclusions as durable knowledge.
