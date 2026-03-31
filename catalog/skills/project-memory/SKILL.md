---
name: project-memory
description: |
  Use when maintaining project knowledge files. Captures factual domain and
  procedural knowledge, logs deterministic and infrastructure errors correctly,
  and keeps the knowledge tree clean over time.
---

# Project Memory

Use this skill when a project stores durable knowledge in markdown files.

## Knowledge Model

Track two kinds of knowledge:

- Domain knowledge: what things are
- Procedural knowledge: how to do things

Organize it as a hierarchy:

- `knowledge/INDEX.md` routes to categories
- category files hold the detailed facts
- read top-down and load only what you need

## Error Logging

Log errors in `ERRORS.md` or the project's equivalent.

- Deterministic errors: conclude immediately and capture the lesson
- Infrastructure errors: log the event first and wait for a pattern before
  concluding root cause

Move stable conclusions out of the error log and into the appropriate domain or
procedural file.

## Maintenance

- Review relevant knowledge files at session start
- Merge overlapping categories
- Split files that grow too large
- Remove stale knowledge
- Add new categories when patterns emerge
- Propose updates to project instructions when repeated lessons should become
  rules
