# Project Extensions for `launch-work` and `land-work`

The `launch-work` and `land-work` skills support project-supplied
extensions at two boundaries — `pre` (skill entry) and `post` (skill
exit) — in two flavors:

- **Hooks** are executable scripts. They gate the skill via exit codes
  (0 pass, 75 human handoff, other non-zero failure).
- **Actions** are markdown files the agent reads and applies as
  additive prose guidance, with an optional `## Stop conditions`
  section that halts the skill if any predicate matches.

Both are optional. A repo with no extensions installed runs the skills
exactly as before.

## When each position fires

| Skill         | Position | Fires at                                                   |
|---------------|----------|------------------------------------------------------------|
| `launch-work` | `pre`    | After worktree verify, before deps install                 |
| `launch-work` | `post`   | After ready-to-land checkpoint, before skill returns       |
| `land-work`   | `pre`    | Before merge preview / rebase / merge                      |
| `land-work`   | `post`   | After merge succeeds (advisory: failures surface, do not unwind) |

## Where extensions live

```
<root>/<skill>/{hooks,actions}/{pre,post}/<two-digit>-<slug>.{sh,md}
```

`<root>` is one of (in precedence order):

1. `<repo>/.agent-plugins/bento/bento/`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/`
3. `~/.config/agent-plugins/bento/bento/` (when `XDG_CONFIG_HOME` is unset)

The two-digit prefix sets execution order (10, 20, 30…). Files without
the prefix are ignored with a warning.

## Worked example: a hook + an action

Suppose your project wants two project-specific extensions:

1. A check at `launch-work/pre` that refuses to launch if a Goose
   migration is pending — fast fail before deps install.
2. A note at `land-work/pre` reminding the agent to regenerate
   GraphQL bindings if the schema changed in this branch.

### 1. The pre-launch hook

Create `.agent-plugins/bento/bento/launch-work/hooks/pre/10-pending-migration.sh`:

```sh
#!/bin/sh
# Refuse launch when a goose migration is pending.
pending=$(goose -dir db/migrations status 2>/dev/null | awk '/Pending/ {print $2}')
if [ -n "$pending" ]; then
  echo "Pending migration: $pending"
  echo "Run 'goose up' before launching new work."
  exit "${BENTO_HOOK_REQUIRES_HUMAN:-75}"
fi
exit 0
```

Make it executable:

```bash
chmod +x .agent-plugins/bento/bento/launch-work/hooks/pre/10-pending-migration.sh
```

When `launch-work` runs, this hook fires after the worktree is verified.
Exit `75` triggers human handoff: the skill halts, surfaces the hook's
stdout to the user, and preserves the branch and worktree.

### 2. The pre-land action

Create `.agent-plugins/bento/bento/land-work/actions/pre/10-regen-graphql.md`:

````markdown
# Regenerate GraphQL bindings before landing

## Context

Applied at `land-work/pre`, before the merge preview is created.

## Body

If `git diff origin/main..HEAD --name-only` lists any file under
`schema/` or `*.graphql`, regenerate gqlgen + gql.tada artifacts in the
feature-branch worktree before proceeding with the merge:

1. Run `go generate ./graph/...` from the repo root.
2. Run `pnpm graphql-codegen` from the frontend root.
3. Stage and commit any newly generated files with message
   `chore: regenerate graphql bindings`.
4. Continue with the rest of `land-work`.

## Stop conditions

- The schema diff is non-empty AND `go generate` exits non-zero. The
  agent should stop and surface the generator output instead of
  attempting to merge stale bindings.
````

When `land-work` runs and the `pre` hooks all pass, the agent reads
this action and applies its guidance. If the schema changed and
generation fails, the matched stop condition halts the skill.

## Available environment for hooks

Hooks receive these env vars (subset; see
[`project-hooks.md`](../catalog/skills/launch-work/references/project-hooks.md)
for the full list):

- `BENTO_HOOK_PHASE` — `launch-work` or `land-work`
- `BENTO_HOOK_POSITION` — `pre` or `post`
- `BENTO_HOOK_REPO_ROOT`, `BENTO_HOOK_WORKTREE`, `BENTO_HOOK_BRANCH`
- `BENTO_HOOK_BASE_REF`, `BENTO_HOOK_BASE_SHA`, `BENTO_HOOK_HEAD_SHA`
- `BENTO_HOOK_MERGE_SHA`, `BENTO_HOOK_LANDED` — set only at `land-work/post`
- `BENTO_HOOK_TTY` — `1` if stdin is a TTY, `0` otherwise
- `BENTO_HOOK_TIMEOUT` — seconds (opt-in), or empty for none
- `BENTO_HOOK_REQUIRES_HUMAN` — `75`

## Discovering installed extensions

To list what extensions a project has installed at a given position:

```bash
catalog/skills/launch-work/scripts/bento-extensions.py discover \
  --repo-root . --skill launch-work --kind hooks --position pre
```

Output is JSON with `files` (in execution order) and `warnings` (for
files that don't match the prefix convention).

## Full reference

- Hook contract: [`catalog/skills/launch-work/references/project-hooks.md`](../catalog/skills/launch-work/references/project-hooks.md)
- Action contract: [`catalog/skills/launch-work/references/project-actions.md`](../catalog/skills/launch-work/references/project-actions.md)
- Design: [`docs/specs/2026-05-06-launch-land-extension-points-design.md`](specs/2026-05-06-launch-land-extension-points-design.md)
