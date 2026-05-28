# Project Hook Script Contract

Use this reference when `launch-work` or `land-work` needs to run
project-supplied hook scripts. Hook scripts are optional: projects without any
matching executable files behave exactly as if no hook scripts were configured.

## Layout

Hook scripts live under one of these roots, in order of precedence:

1. `<repo-root>/.agent-plugins/bento/bento/`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/`
3. `~/.config/agent-plugins/bento/bento/` when `XDG_CONFIG_HOME` is unset

Within each root, hook scripts are organized by skill, then position:

```
<root>/<skill>/hook-scripts/<position>/<two-digit>-<slug>.<ext>
```

- `<skill>` is `launch-work` or `land-work`
- `<position>` is `pre` or `post`
- `<two-digit>-<slug>` is the filename convention; the prefix is required and
  the slug is freeform
- `<ext>` is any executable type (`.sh`, `.py`, no extension, etc.); only the
  executable bit matters

For example, repo-scoped hook scripts may live at
`<repo-root>/.agent-plugins/bento/bento/launch-work/hook-scripts/pre/` and
`<repo-root>/.agent-plugins/bento/bento/land-work/hook-scripts/pre/`.

User-global hook scripts may live at
`~/.config/agent-plugins/bento/bento/launch-work/hook-scripts/pre/` when
`XDG_CONFIG_HOME` is unset, or under `$XDG_CONFIG_HOME/agent-plugins/bento/bento/`
otherwise.

## When hook scripts fire

| Skill | Position | Fires at | Worktree state |
|---|---|---|---|
| launch-work | pre | After worktree verify, before deps install | Linked worktree exists |
| launch-work | post | Before declaring the work ready to land | Linked worktree exists |
| land-work | pre | Before merge preview/rebase/merge | Feature-branch worktree |
| land-work | post | After merge succeeds, before skill returns | Feature-branch worktree |

## Filename convention

Each hook script filename **must** start with two decimal digits and a hyphen:
`<two-digit>-<slug>`. Files are sorted by ascending numeric prefix; ties
break by lexicographic filename order. Leave gaps (10, 20, 30…) so later
additions can slot between existing hook scripts without renumbering. Files that
don't match the prefix convention are ignored with a warning.

Hidden files (leading dot), editor backups (`~`, `.bak`, `.swp`, `.orig`),
and non-executable files are silently ignored.

## Discovery and execution

The skill invokes:

```
catalog/skills/launch-work/scripts/run-lifecycle-extensions.py run-hooks \
  --repo-root <repo> --skill <skill> --position <pre|post> \
  --branch <branch> --worktree <worktree> ...
```

Hook scripts at a position run sequentially. The first non-zero exit halts further
hook scripts at that position (except in advisory mode — see below).

The working directory is the linked worktree (launch-work) or feature-branch
worktree (land-work).

## Environment

| Variable | Meaning |
|---|---|
| `BENTO_HOOK_PHASE` | `launch-work` or `land-work` |
| `BENTO_HOOK_POSITION` | `pre` or `post` |
| `BENTO_HOOK_REPO_ROOT` | Absolute repo root |
| `BENTO_HOOK_WORKTREE` | Absolute worktree path |
| `BENTO_HOOK_BRANCH` | Current task or feature branch |
| `BENTO_HOOK_BASE_REF` | Primary-branch ref name |
| `BENTO_HOOK_BASE_SHA` | SHA of base ref when known |
| `BENTO_HOOK_HEAD_SHA` | SHA of feature-branch head when known |
| `BENTO_HOOK_MERGE_SHA` | Merge commit SHA; set only at `land-work/post` |
| `BENTO_HOOK_LANDED` | `1` only at `land-work/post` once merge is complete |
| `BENTO_HOOK_RUNTIME` | `claude`, `codex`, or `unknown` |
| `BENTO_HOOK_TASK_ID` | Tracker item ID when available |
| `BENTO_HOOK_TTY` | `1` if stdin is a TTY, else `0` |
| `BENTO_HOOK_TIMEOUT` | Seconds, or empty for no timeout |
| `BENTO_HOOK_REQUIRES_HUMAN` | `75` |

Unavailable values are set to empty strings, not omitted.

## Exit codes

- `0` — pass; continue.
- `75` (`EX_TEMPFAIL`) — human handoff. Halt, preserve branch and linked
  worktree, surface stdout as the handoff message, do not perform
  destructive cleanup.
- Any other non-zero — failure. Halt, surface stdout and stderr, preserve
  branch and linked worktree.

### Advisory mode (`land-work/post` only)

After a successful merge, abort cannot reverse the landing. The skill runs
`land-work/post` hook scripts in advisory mode: non-zero exits surface the
message but do not unwind the merge or block tracker mutations. Continue
running remaining hook scripts past a failure.

## Timeouts

There is no built-in timeout. Interactive hook scripts (`gh auth login`,
passphrase prompts) work without ceremony. The agent surfaces a soft
heartbeat message after long quiet stretches; Ctrl-C reaches the running
hook script directly.

A repo that wants a bounded run sets `BENTO_HOOK_TIMEOUT=<seconds>` (e.g.,
in repo-local environment for CI). Default unset means no timeout. Hook scripts
that exceed the timeout are killed and reported with exit code `124`.

Hook scripts that need to detect a non-interactive context can check
`BENTO_HOOK_TTY`:

```sh
#!/bin/sh
if [ "$BENTO_HOOK_TTY" != "1" ]; then
  echo "This hook script needs an interactive terminal."
  exit "$BENTO_HOOK_REQUIRES_HUMAN"
fi
exec gh auth login
```

## Reference examples

No-op:

```sh
#!/bin/sh
exit 0
```

Human-handoff:

```sh
#!/bin/sh
cat <<'MESSAGE'
Human review required before this branch can land.
Review the generated artifacts, then rerun land-work.
MESSAGE
exit "${BENTO_HOOK_REQUIRES_HUMAN:-75}"
```

Conditional based on phase and position:

```sh
#!/bin/sh
case "$BENTO_HOOK_PHASE/$BENTO_HOOK_POSITION" in
  launch-work/pre)  echo "post-bootstrap check"; exit 0 ;;
  launch-work/post) echo "ready-to-land sanity check"; exit 0 ;;
  *)                exit 0 ;;
esac
```
