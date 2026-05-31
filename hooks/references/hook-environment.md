# Hook Execution Environment

Canonical reference for the runtime environment that Claude Code hooks execute
in. Read this before writing a hook that depends on environment variables, file
paths, shell features, or process capabilities.

## Working Directory

Hooks run from `$HOME`, not from the project root or the directory Claude Code
was invoked in.

```bash
# WRONG — $PWD is $HOME, not the project
repo_root=$(git rev-parse --show-toplevel)

# CORRECT — read cwd from the JSON payload on stdin
cwd=$(jq -r '.cwd // empty' <<< "$PAYLOAD")
repo_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
```

The `cwd` field is present in all hook payloads that carry tool context
(PreToolUse, PostToolUse). SessionStart and Stop payloads carry a
`transcript_path` but not a `cwd`.

## Environment Variable Inheritance

Hooks **do inherit** the full environment that Claude Code itself was launched
with. This includes:

- User-defined variables (`DOTFILES`, `GOPATH`, `CARGO_HOME`, `NVM_DIR`, etc.)
- Terminal and session variables (`TMUX`, `TMUX_PANE`, `TERM`, `DISPLAY`)
- SSH agent forwarding (`SSH_AUTH_SOCK`)
- Homebrew and other package manager prefixes

Claude Code also injects several variables before spawning any subprocess,
including hooks:

| Variable | Value |
|---|---|
| `CLAUDECODE` | `1` |
| `CLAUDE_CODE_SESSION_ID` | UUID for the current session |
| `CLAUDE_CODE_TMPDIR` | Isolated temp directory for this session |
| `AI_AGENT` | `claude-code_<version>_agent` |

Plugin bin directories are prepended to `PATH` at startup, so binaries
installed by plugins are available to hooks.

### What is NOT inherited

Shell rc files (`.bashrc`, `.zshrc`, `.profile`) are **not** re-sourced for
hook subprocesses. The hook process is non-interactive, so:

- Shell **functions** defined in rc files are not available.
- Shell **aliases** are not available.
- Dynamic shell state made after Claude was launched is not visible. For
  example, if `nvm use 20` was run in the parent terminal *after* Claude
  started, the hook will not see Node.js 20 in its PATH — but `NVM_DIR` will
  be set because it was exported before Claude launched.

**Practical rule:** if a variable or PATH entry was present in the shell that
launched Claude, it is present in hooks. If it was added or changed afterward,
it is not.

## stdin

Hooks receive a JSON payload on stdin. The shape varies by event:

| Event | Key fields |
|---|---|
| `PreToolUse` | `tool_name`, `tool_input`, `session_id`, `cwd` |
| `PostToolUse` | `tool_name`, `tool_input`, `tool_response`, `session_id`, `cwd` |
| `SessionStart` | `session_id`, `transcript_path` |
| `Stop` | `session_id`, `transcript_path`, `stop_hook_active` |
| `UserPromptSubmit` | `session_id`, `transcript_path`, `prompt` |

stdin is **never a TTY**. Do not use `read` with a TTY assumption, and do not
use `tput` or terminal escape sequences in hook stdout.

Read stdin exactly once at the top of the script:

```bash
PAYLOAD=$(cat)
tool_name=$(jq -r '.tool_name // empty' <<< "$PAYLOAD")
cwd=$(jq -r '.cwd // empty' <<< "$PAYLOAD")
```

## stdout and stderr

**stdout** is interpreted for structured JSON decisions. Anything that is not a
valid `hookSpecificOutput` JSON object is ignored by the runtime (not shown to
the model, not shown to the user). Write only a single JSON object to stdout
when you intend to return a decision; do not mix debug text with JSON.

**stderr** is surfaced to the model as context when the hook exits with a
blocking code (`2`). For non-blocking exits (`0`), stderr is logged but not
surfaced.

## Shell and Process Model

Hooks are spawned as non-interactive subprocesses of Claude Code. The command
string from `settings.json` is passed to the system shell for evaluation, so
variable expansion in the command string (e.g., `$DOTFILES/scripts/foo.sh`) is
expanded at launch time using the inherited environment.

The hook process is **not a login shell** and **not an interactive shell**. Do
not depend on `.bashrc`, `.profile`, or any rc-file initialization.

## TTY Status

No file descriptor is a TTY inside a hook:

- stdin: JSON pipe (not a TTY)
- stdout: pipe to Claude Code's decision handler (not a TTY)
- stderr: pipe to Claude Code's log handler (not a TTY)

Do not call interactive programs (`vim`, `less`, `fzf`, etc.) from hooks.
Tools that detect TTY absence and fall back to non-interactive mode (e.g.,
`git diff --no-color`) work correctly.

## Timeouts

Claude Code enforces a 60-second timeout on hook execution by default. Hooks
that exceed the timeout are killed and treated as a non-blocking failure (the
tool call proceeds). Design hooks to complete quickly; avoid network calls on
the critical path.

## Network Access

Hook processes inherit the same network access as Claude Code. There is no
sandbox. Hooks can make outbound HTTP requests, connect to local sockets
(including `SSH_AUTH_SOCK`), and access the filesystem without restriction.

## Common Invalid Assumptions

| Assumption | Reality |
|---|---|
| `$PWD` is the project root | `$PWD` is `$HOME`. Read `cwd` from the JSON payload. |
| `exit 1` blocks a tool call | `exit 1` is a **non-blocking failure**; the tool proceeds. Use `exit 2` to block. |
| Shell functions from `.bashrc` are available | Non-interactive shell; rc files are not sourced. |
| NVM/pyenv shims are always in PATH | Only if they were in PATH when Claude was launched. |
| Activated virtualenvs are visible | Only if `VIRTUAL_ENV` was set before Claude started. |
| Hook stdout is shown to the user | Only a `hookSpecificOutput` JSON object is interpreted; other stdout is discarded. |
| Hooks run concurrently with the tool | PreToolUse hooks block the tool call; PostToolUse hooks run after it returns. |
| SessionStart hooks can set env vars for later hooks | Child processes cannot modify parent environment; env changes in hooks are not propagated. |

## See Also

- [`hook-contract.md`](hook-contract.md) — exit codes, JSON decision shapes, blocking vs. non-blocking semantics
- [`../README.md`](../README.md) — hook layout and platform peer structure
