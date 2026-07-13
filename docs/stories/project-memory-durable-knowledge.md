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
An agent discovers that the repo's integration tests require a specific Postgres DSN that is not documented anywhere. Rather than rediscovering this next session, it invokes project-memory to record the fact. The skill first reads the repo's documented memory structure — where durable knowledge lives, whether domain facts and procedures are separated, whether there is a dedicated error log, and which files act as indexes. It writes the DSN requirement to the appropriate file in the existing structure, using the repo's conventions. On a separate occasion, a repeated migration failure is logged to the error log with a date stamp and a reference to the commit that triggered it. Neither write invents a new folder structure or file name.

## Expected Behavior
- The repo's documented memory structure is read before any write.
- Domain knowledge (what things are) and procedural knowledge (how to do things) are kept separate if the repo already separates them.
- An error log entry is date-stamped and appended, not overwritten.
- No new folder structure or file names are invented without explicit repo or user approval.
- Index and routing files are updated when a new file is added to the memory structure.

## Boundaries
- Does not apply to repos that do not document a durable knowledge structure.
- Does not invent memory conventions without approval.
- Does not duplicate content already derivable from the code or git history.

## Auditable Claims
- The SKILL.md states: "Do not assume every repo uses the same folder names or file names."
- The SKILL.md states: "If the repo does not document a durable knowledge structure, do not invent one without user or repo-level approval."
- The skill tracks two knowledge kinds: domain knowledge and procedural knowledge.

## Evidence
### Tests
### Surface
- `skill: project-memory`
### Docs
- `catalog/skills/project-memory/SKILL.md`
