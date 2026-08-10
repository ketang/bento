---
schema_version: 1
title: Project Memory Captures and Maintains Durable Repo Knowledge
slug: project-memory-durable-knowledge
status: active
authority: observed
change_resistance: low
tests_applicable: false
locked_sections:
  - Intent
---

# Project Memory Captures and Maintains Durable Repo Knowledge

## Intent
When a repo maintains durable knowledge files for future sessions, project-memory captures new facts, logs errors, and keeps the documented memory structure clean without inventing its own conventions.

## Story
An agent discovers that the repo's integration tests require a specific Postgres DSN that is not documented anywhere. Rather than rediscovering this next session, it invokes project-memory to record the fact. The skill first reads the repo's documented memory structure — where durable knowledge lives, whether domain facts and procedures are separated, whether there is a dedicated error log, and which files act as indexes. It writes the DSN requirement to the appropriate file in the existing structure, using the repo's conventions. On a separate occasion, a migration keeps failing for infrastructure reasons: the skill logs the event to the repo's error log first and waits for a pattern before concluding a root cause, rather than writing a premature conclusion. Once the conclusion is stable, it moves out of the error log into the appropriate domain or procedural file. Neither write invents a new folder structure or file name.

## Expected Behavior
- The repo's documented memory structure is read before any write.
- Domain knowledge (what things are) and procedural knowledge (how to do things) are kept separate if the repo already separates them.
- Deterministic errors are concluded immediately with the lesson captured; infrastructure errors are logged first and left open until a pattern emerges.
- Stable conclusions are moved out of the error log into the appropriate domain, procedural, or routing file.
- No new folder structure or file names are invented without explicit repo or user approval.

## Boundaries
- Does not apply to repos that do not document a durable knowledge structure.
- Does not invent memory conventions without approval.
- Does not assume `knowledge/INDEX.md` or `ERRORS.md` exists.
- Does not treat speculative conclusions as durable knowledge.

## Auditable Claims
- The SKILL.md states: "Do not assume every repo uses the same folder names or file names."
- The SKILL.md states: "If the repo does not document a durable knowledge structure, do not invent one without user or repo-level approval."
- The skill tracks two knowledge kinds: domain knowledge and procedural knowledge.
- The SKILL.md "Error Logging" section distinguishes deterministic errors ("conclude immediately and capture the lesson") from infrastructure errors ("log the event first and wait for a pattern before concluding root cause").

## Evidence
### Tests
### Surface
- `skill: project-memory`
### Docs
- `catalog/skills/project-memory/SKILL.md`
