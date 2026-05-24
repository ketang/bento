# Project Hook Skill Contract

Use this reference when `launch-work` or `land-work` needs to apply
project-supplied hook skills. Hook skills are markdown files the agent reads
and applies as additive guidance — distinct from hook scripts (executables that
gate). Hook skills are optional.

## Layout

Hook skills live in the same XDG-precedence chain as hook scripts:

1. `<repo-root>/.agent-plugins/bento/bento/`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/`
3. `~/.config/agent-plugins/bento/bento/`

Within each root:

```
<root>/<skill>/hook-skills/<position>/<two-digit>-<slug>.md
```

- `<skill>` is `launch-work` or `land-work`
- `<position>` is `pre` or `post`

For example, repo-scoped hook skills may live at
`<repo-root>/.agent-plugins/bento/bento/launch-work/hook-skills/pre/` and
`<repo-root>/.agent-plugins/bento/bento/land-work/hook-skills/pre/`.

User-global hook skills may live at
`~/.config/agent-plugins/bento/bento/launch-work/hook-skills/pre/` when
`XDG_CONFIG_HOME` is unset, or under `$XDG_CONFIG_HOME/agent-plugins/bento/bento/`
otherwise.

Hook skills deliberately do not have a slot mid-skill. Mid-skill is hook script
territory (deterministic gates that can abort). Hook skills stay at boundaries.

## When hook skills fire

Same per-skill timings as hook scripts. At each position, **hook scripts run first**;
if all hook scripts pass (exit 0), the agent reads hook skill files in
numeric-prefix order and applies each before moving to the next.

If any hook script returns non-zero (other than in advisory mode at
`land-work/post`), hook skills for that position do not load.

## Filename convention

Same as hook scripts. Two-digit numeric prefix required:
`<two-digit>-<slug>.md`. Files without the prefix are ignored with a
warning. Files with extensions other than `.md` are ignored silently.

## Authoring shape

A typical hook skill file:

```markdown
# Hook skill title (optional H1)

## Context

Optional. Describe what state the hook skill assumes (e.g., "linked worktree
exists; progress log is at worktree-ready").

## Body

Plain prose telling the agent what additional rules to apply for the rest
of this position's work. Hook skills are *additive* and may *modify* default
behavior. They must not direct full replacement of the skill's built-in
workflow.

## Stop conditions

Optional. A list of predicates the agent evaluates at apply time. If any
match, the agent halts, surfaces the matched condition, and preserves
branch and linked worktree (mirroring exit-75 semantics for hook scripts).

- Predicate one (in plain language; agent uses tools to verify)
- Predicate two
```

The `## Stop conditions` section name is the only structured convention.
Everything else is free-form markdown.

## Advisory mode (`land-work/post` only)

After a successful merge, halt cannot reverse the landing. Stop conditions
matched at `land-work/post` are advisory: the agent surfaces the matched
condition but does not unwind the merge or block tracker mutations.
Subsequent hook skills continue to apply.

## Discovery

The skill invokes:

```
catalog/skills/launch-work/scripts/run-lifecycle-extensions.py discover \
  --repo-root <repo> --skill <skill> --kind hook-skills --position <pre|post>
```

The output is a JSON list of file paths in execution order, plus any
warnings (e.g., missing-prefix filenames). The agent reads each file in
order and applies it.

## Reference example

`30-warn-on-uncommitted-config.md`:

```markdown
# Warn on uncommitted config

## Context

Assumes the linked worktree exists. Applied at `launch-work/post`.

## Body

Before reporting that the work is ready to land, run `git status -s` in
the worktree and surface any tracked configuration files (e.g.,
`config/*.yaml`, `.env.example`) that have uncommitted modifications. Do
not block; this is a soft prompt for the user to confirm intent.

## Stop conditions

- The repository contains a `LICENSE.draft` file at the repo root. Verify
  with `test -f "$BENTO_HOOK_REPO_ROOT/LICENSE.draft"`.
```
