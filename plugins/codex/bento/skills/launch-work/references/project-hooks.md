# Project Hook Contract

Use this reference when `launch-work` or `land-work` needs to run
project-supplied extension hooks. Hooks are optional: projects without any
matching executable hook files behave exactly as they did before this contract.

## Discovery

Discover executable hook files from these directories, in order:

1. `<repo-root>/.agent-plugins/bento/bento/hooks/<phase>/`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/hooks/<phase>/`
3. `~/.config/agent-plugins/bento/bento/hooks/<phase>/` when
   `XDG_CONFIG_HOME` is unset

`<phase>` is one of:

- `launch-work`
- `land-work`

For example, repo-scoped hooks may live at
`<repo-root>/.agent-plugins/bento/bento/hooks/launch-work/` and
`<repo-root>/.agent-plugins/bento/bento/hooks/land-work/`.

Within each existing phase directory, run regular executable files in
lexicographic filename order. Ignore directories, non-executable files, hidden
files, editor backups, and files whose names contain path separators. Do not
interpret the directory contents beyond executable discovery; each hook is an
opaque project-owned program.

## Execution

Run each hook as a separate process from the repository root. Do not source hook
files into the current shell. Do not continue to later hooks after any hook
returns a non-zero exit code.

Provide these environment variables when known:

- `BENTO_HOOK_PHASE`: `launch-work` or `land-work`
- `BENTO_HOOK_REPO_ROOT`: absolute repository root
- `BENTO_HOOK_BRANCH`: current task branch name
- `BENTO_HOOK_BASE_REF`: primary branch ref name or base ref used for the
  current operation
- `BENTO_HOOK_BASE_SHA`: SHA for the base ref when available
- `BENTO_HOOK_HEAD_SHA`: SHA for the current branch head when available
- `BENTO_HOOK_RUNTIME`: `claude`, `codex`, or `unknown`
- `BENTO_HOOK_TASK_ID`: tracker item ID when available
- `BENTO_HOOK_REQUIRES_HUMAN=75`

If a value is not available, set the variable to an empty string rather than
omitting it.

## Exit Codes

- `0`: hook passed; continue.
- `75`: the hook requires human handoff. Stop the skill, preserve the branch
  and linked worktree, surface the hook's stdout as the handoff message, and do
  not perform destructive cleanup or merge operations.
- Any other non-zero code: hook failed. Stop the skill, surface stdout and
  stderr, and leave the branch and linked worktree intact for diagnosis.

For exit `75`, treat stderr as diagnostic detail only. The user-facing handoff
message should be based on stdout so hook authors can provide concise next
steps.

## Phase Timing

`launch-work` runs the `launch-work` hook phase after worktree verification and
before dependency installation, tests, or file edits.

`land-work` runs the `land-work` hook phase before creating or verifying the
merge preview, rebasing, or merging.

## Reference Examples

No-op launch hook:

```sh
#!/bin/sh
exit 0
```

Human-handoff land hook:

```sh
#!/bin/sh
cat <<'MESSAGE'
Human review is required before this branch can land.
Review the generated project artifacts, then rerun land-work from this
feature-branch worktree.
MESSAGE
exit "${BENTO_HOOK_REQUIRES_HUMAN:-75}"
```
