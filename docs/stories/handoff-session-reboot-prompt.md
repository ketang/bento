---
schema_version: 1
title: Handoff Writes a Session Reboot Prompt
slug: handoff-session-reboot-prompt
status: active
authority: observed
change_resistance: low
tests_applicable: true
locked_sections:
  - Intent
---

# Handoff Writes a Session Reboot Prompt

## Intent
When context-window pressure builds or the user delegates remaining work, the handoff skill distills the current session state into a structured markdown prompt and writes it to `/tmp/` so the next session or teammate can resume without losing context.

## Story
An agent is deep into a multi-step implementation task when the context window approaches compaction limits. The user invokes `/handoff`. The skill checks that the current directory is inside a git repo and that HEAD is on a named branch, then gathers: the current branch name, a summary of in-flight work, the next concrete action, any open questions, decisions made, files changed, and a "do not redo" list of already-completed steps. It writes this into a seven-slot markdown file under `/tmp/` with a predictable name, then echoes the full contents back to the chat. The user copies the file path or contents into a new session prompt, and the next agent resumes with full context.

## Expected Behavior
- The skill requires the working directory to be inside a git repo on a named branch.
- It writes a markdown file to `/tmp/` with seven labeled slots.
- The file contents are echoed back to the chat immediately after writing.
- The output is a self-contained prompt a fresh agent can consume without reading the prior conversation.
- The skill does not invoke a subagent or teammate; it only writes and echoes.

## Boundaries
- Not designed for state that must survive long gaps (days or weeks).
- Does not apply inside an active expedition — defer to the expedition skill's session-end protocol.
- Does not dispatch the next agent; the user is responsible for starting a new session with the handoff file.

## Auditable Claims
- The SKILL.md states the output file is written under `/tmp/`.
- The SKILL.md documents exactly seven labeled slots.
- The skill short-circuits if the working directory is not inside a git repo or HEAD is detached.

## Evidence
### Tests
### Surface
- `skill: handoff`
### Docs
- `catalog/skills/handoff/SKILL.md`
