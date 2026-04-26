---
name: handoff
description: Use when the current session needs a structured reboot prompt — context-window pressure, delegation to a teammate, or any user-initiated session handoff. Writes a markdown file under /tmp/ with seven labeled slots and echoes the contents back to chat.
recommended_model: high
---

# Handoff

## Model Guidance

Recommended model: high.

This skill's load-bearing task is distilling in-flight conversation state into a
crisp next-action paragraph. That distillation benefits from a higher-capability
model. Lower-capability models will produce vague summaries that defeat the
purpose of the prompt.

## When to use

- Context-window pressure: the current session is approaching compaction.
- Delegation: the user is handing remaining work to a different session, role,
  or person.
- General user-initiated handoff: the user invoked `/handoff` directly.

## When NOT to use

- A long-idle resumption ("pick up next week"). `/handoff` is not designed for
  state that must survive long gaps.
- Subagent dispatch. The skill writes a file the user will read or copy; it
  does not feed the prompt to the Agent tool.
- Inside an active expedition. Defer to the expedition skill's session-end
  protocol (update `docs/expeditions/<name>/handoff.md` via
  `expedition/scripts/expedition.py`).

## Preconditions and short-circuit behavior

The skill operates only when all three preconditions hold:

1. The current working directory is inside a git repository.
2. HEAD resolves to a named branch (not detached).
3. No active expedition is detected in the current worktree.

When any precondition fails, the helper exits non-zero with a one-line
diagnostic and writes nothing.

## Template structure

The agent fills body content under each of these seven labeled headings, in
order:

1. **Next action** — the single concrete next step for the new session.
2. **Original task** — the user's original request, in one line.
3. **Branch & worktree** — current branch, worktree path, primary branch.
4. **Verification state** — what was run, what passed, what failed, what was
   not yet tested.
5. **Decisions & dead-ends** — non-obvious choices, approaches ruled out and
   why.
6. **Pending decisions / blockers** — questions waiting on the user, external
   blockers.
7. **Notes** — free-form prose for in-flight reasoning that does not fit a
   slot.

The on-disk template is editable. A user override (repo-scope or home-scope)
may add, remove, rename, or reorder headings; the agent's runtime job is to
write content under whatever headings the resolved template provides.

## Customization

The template is resolved through the `agent-plugins` convention:

1. `<repo-root>/.agent-plugins/bento/bento/handoff/template.md`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/handoff/template.md`
   (default `~/.config/agent-plugins/bento/bento/handoff/template.md` when
   `XDG_CONFIG_HOME` is unset)
3. The plugin-bundled default at `handoff/references/templates/handoff.md`.

First match wins. Lookup is per-file. Users override only the file they want
to override; missing files fall through.

## Workflow

1. Read the user's stated reason for handoff (if any) and review the
   conversation state.
2. Compose body text under each heading from the resolved template. Be
   concrete; the next agent will not see this conversation.
3. Run the helper:

```bash
handoff/scripts/handoff.py --input <path-to-filled-template>
```

   On the primary branch, also pass `--slug <kebab-case-summary>` (2–4 words).
   Use `--input -` to pipe content via stdin instead of writing to a temp file.

4. The helper prints the absolute path of the file it wrote to stdout.
5. Echo the full contents of the file back to chat in the same response so the
   user can see what was captured without opening the file.

Invoke the helper by script path (`handoff/scripts/handoff.py ...`) so
approvals stay scoped to the script.

## Output filename

```
/tmp/handoff-<suffix>-<YYYYMMDD-HHMMSS>.md
```

`<suffix>` is the current branch name with `/` and other non-`[A-Za-z0-9._-]`
characters replaced with `-`. On the primary branch (where there is no useful
branch suffix), `<suffix>` is the agent-supplied `--slug`.

## Non-Negotiable Rules

- Do not write a file when preconditions fail.
- Do not invent a branch name when HEAD is detached.
- Do not duplicate or replace the expedition skill's `handoff.md` when an
  expedition is active.
- Do not perform `{{token}}` substitution on the template; write prose under
  each heading.
- Do not modify a repo-scope or home-scope user-edited template; treat both as
  read-only.
- Do not chat-only the output. Always write the file when preconditions pass.
- Always echo the file contents in chat after writing.

## Stop conditions

Stop and ask the user if:

- The conversation contains no clear next action and you cannot infer one with
  reasonable confidence.
- An expedition is active. Defer to the expedition skill's session-end flow.
- Multiple unrelated threads are in flight and a single handoff would
  misrepresent the state. Suggest the user pick the thread to capture.
