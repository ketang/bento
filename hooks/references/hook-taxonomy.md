# Hook Taxonomy: Three Different Things Called "Hooks"

"Hook" is overloaded in this repo. Three unrelated mechanisms share the name and
have **completely different execution environments**. Before reasoning about what
a hook can rely on, identify which kind you have.

| Kind | Who runs it | When | Environment reference |
|---|---|---|---|
| **Agent-runtime hook** | The coding agent (Claude Code / Codex CLI) | Agent lifecycle events (`PreToolUse`, `SessionStart`, …) | [`hook-environment.md`](hook-environment.md) (Claude), [`codex-hook-environment.md`](codex-hook-environment.md) (Codex) |
| **Lifecycle-extension hook script** | A bento skill's Python runner | `launch-work` / `land-work` `pre`/`post` boundaries | This doc, [§ hook scripts](#2-lifecycle-extension-hook-scripts) |
| **Lifecycle-extension hook skill** | The agent itself (reads markdown) | Same boundaries as above | This doc, [§ hook skills](#3-lifecycle-extension-hook-skills) |

## 1. Agent-runtime hooks

Command hooks registered in the agent's own configuration
(`~/.claude/settings.json`, `~/.codex/hooks.json`, or a plugin `hooks.json`
sourced from `catalog/hooks/`). The **agent runtime** spawns them as
subprocesses on lifecycle events and interprets their exit code and stdout JSON.

- Spawned by: the agent runtime (a separate process from any skill).
- Input: a JSON payload on stdin (`tool_name`, `cwd`, `session_id`, …).
- Contract: exit `0` allow / exit `2` block; optional `hookSpecificOutput` JSON.
  See [`hook-contract.md`](hook-contract.md).
- Environment: **runtime-specific and materially different between Claude and
  Codex** — working directory, injected vars, and sandbox behavior all differ.
  See the two environment references above. The single portable rule: read `cwd`
  from the payload, never `$PWD`.

These are the hooks in `catalog/hooks/` (`bento`, `hygiene`, `session-id`,
`telemetry`).

## 2. Lifecycle-extension hook scripts

Project-supplied executable scripts that extend the `launch-work` and
`land-work` skills at their `pre`/`post` boundaries. They live at:

```
<root>/<skill>/hook-scripts/{pre,post}/<NN>-<slug>.sh
```

and are discovered and run by `run-lifecycle-extensions.py` — **not** by the
agent runtime. Their environment is nothing like an agent-runtime hook:

- Spawned by: the skill's Python runner, in-process during the skill.
- Input: **no stdin JSON payload.** Context arrives as `BENTO_HOOK_*` environment
  variables the runner sets deliberately (`BENTO_HOOK_PHASE`,
  `BENTO_HOOK_POSITION`, `BENTO_HOOK_REPO_ROOT`, `BENTO_HOOK_WORKTREE`,
  `BENTO_HOOK_BRANCH`, `BENTO_HOOK_BASE_SHA`, `BENTO_HOOK_HEAD_SHA`,
  `BENTO_HOOK_MERGE_SHA`/`BENTO_HOOK_LANDED` at `land-work/post`,
  `BENTO_HOOK_TTY`, `BENTO_HOOK_TIMEOUT`, `BENTO_HOOK_REQUIRES_HUMAN`).
- Contract: exit `0` pass, exit `75` (`BENTO_HOOK_REQUIRES_HUMAN`) human handoff,
  any other non-zero fail. This is a **different exit-code vocabulary** from
  agent-runtime hooks (where `2`, not `75`, is the meaningful non-zero code).
- Working directory / cwd: do not infer from an agent-runtime rule. Use
  `BENTO_HOOK_REPO_ROOT` / `BENTO_HOOK_WORKTREE`, which the runner sets
  explicitly.

Full contract:
[`../../catalog/skills/launch-work/references/project-hook-scripts.md`](../../catalog/skills/launch-work/references/project-hook-scripts.md).
Overview and worked example: [`../../docs/extensions.md`](../../docs/extensions.md).

## 3. Lifecycle-extension hook skills

Markdown files at:

```
<root>/<skill>/hook-skills/{pre,post}/<NN>-<slug>.md
```

There is **no subprocess and no environment at all.** The agent *reads* the
markdown and applies it as additive prose guidance, with an optional
`## Stop conditions` section that halts the skill if a predicate matches.
"Environment" questions (env vars, cwd, stdin, PATH) do not apply — the only
"runtime" is the agent's own context window.

Full contract:
[`../../catalog/skills/launch-work/references/project-hook-skills.md`](../../catalog/skills/launch-work/references/project-hook-skills.md).

## Why this matters

Assumptions from one kind are wrong for another:

- A lifecycle-extension hook **script** that tries to `jq` a payload off stdin
  gets nothing — its context is `BENTO_HOOK_*` env vars, not stdin JSON.
- An agent-runtime hook that expects `BENTO_HOOK_REPO_ROOT` gets nothing — that
  variable exists only inside the skill runner.
- `exit 2` blocks an agent-runtime tool call but is just a generic failure to
  the lifecycle-extension runner, which reserves `75` for human handoff.
- "Hooks run from `$HOME`" is a Claude agent-runtime fact. It is false for Codex
  agent-runtime hooks (workspace dir) and irrelevant for hook scripts (use
  `BENTO_HOOK_*`) and hook skills (no process).
