# Codex Hook Execution Environment

Canonical reference for the runtime environment that **Codex CLI** hooks execute
in. Read this before writing a codex hook (`~/.codex/hooks.json` or a plugin
`hooks.json`) that depends on the working directory, environment variables,
stdin shape, or filesystem writes.

The Claude Code equivalent is [`hook-environment.md`](hook-environment.md). The
two runtimes differ in ways that matter — see [Codex vs. Claude](#codex-vs-claude-differences).

## How this was verified

The claims below were checked empirically against `codex-cli 0.144.1` on Linux
by wiring a probe hook into `~/.codex/hooks.json` for `SessionStart`,
`PreToolUse`, and `PostToolUse`, then triggering it with a real `codex exec`
run. The probe dumped its stdin payload, working directory, environment, TTY
status, and shell mode. Raw captured evidence:
[`../experiments/codex-hook-capture-verified.txt`](../experiments/codex-hook-capture-verified.txt);
the probe itself is
[`../experiments/codex-probe.sh`](../experiments/codex-probe.sh). Claims that
could not be positively confirmed in this environment are flagged inline as
**[observed]** or **[unverified]** rather than stated as fact.

Enabling hooks at all requires `[features] hooks = true` in `~/.codex/config.toml`.

## Working Directory

Codex hooks run **from the project/workspace directory** — `$PWD` equals the
`cwd` field in the payload. This is the opposite of Claude Code, where hooks run
from `$HOME`.

```bash
# Codex: $PWD is already the workspace, but still prefer the payload cwd
# for portability with Claude hooks and resilience to future changes.
cwd=$(jq -r '.cwd // empty' <<< "$PAYLOAD")
repo_root=$(git -C "${cwd:-$PWD}" rev-parse --show-toplevel 2>/dev/null)
```

Reading `cwd` from the payload is the portable rule for **both** runtimes: it is
correct on Claude (where `$PWD` is wrong) and correct on Codex.

## stdin Payload

Every codex hook receives a JSON payload on stdin. Unlike Claude, **codex
includes `cwd` on every event, including `SessionStart`.** Fields observed:

| Event | Fields |
|---|---|
| `SessionStart` | `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`, `permission_mode`, `source` |
| `PreToolUse` | above (minus `source`) + `turn_id`, `tool_name`, `tool_input`, `tool_use_id` |
| `PostToolUse` | `PreToolUse` fields + `tool_response` |

Notes:

- `permission_mode` reflects the run's sandbox/approval posture (e.g.
  `bypassPermissions` for a full-access run). It is present on every event.
- `model` is the model id of the run.
- `source` on `SessionStart` distinguishes `startup` from `resume` and is what
  the `matcher` (e.g. `"startup|resume"`) is tested against.
- `tool_input` is an object (e.g. `{"command": "..."}` for a Bash tool).

Read stdin exactly once at the top of the script (`PAYLOAD=$(cat)`), then parse
fields from `$PAYLOAD`. stdin is **not a TTY**.

## Environment Variable Inheritance

Codex hooks **inherit the full environment of the process that launched codex.**
Verified: `DOTFILES`, `NVM_DIR`, `SSH_AUTH_SOCK`, and `TMUX` were all present in
the hook environment.

Stronger evidence of arbitrary/custom inheritance: the captured codex hook
environment also contained `CLAUDECODE=1` and
`AI_AGENT=claude-code_<version>_agent`. Codex does not set those variables —
they were exported by the Claude Code session that launched the codex process,
inherited by codex, and inherited again by the codex hook subprocess. Custom
variables set in an **ancestor** process therefore propagate all the way into
codex hooks.

Codex injects its own variables before spawning hooks:

| Variable | Value |
|---|---|
| `CODEX_API_KEY` | The API key for the run |
| `CODEX_MANAGED_BY_NPM` | `1` when installed via npm |
| `CODEX_MANAGED_PACKAGE_ROOT` | Path to the installed `@openai/codex` package |

Codex also prepends its own entries to `PATH` (an `arg0` shim under
`~/.codex/tmp/arg0/…` and the vendored `codex-path`), so the `codex` binary and
its helpers are on `PATH` inside hooks.

### What is NOT inherited

The hook process is **not a login shell and not interactive**
(`shopt login_shell` = `no`). Shell rc files are not re-sourced, so functions,
aliases, and any dynamic PATH changes made after codex launched are not visible
— same practical rule as Claude: *present when codex launched → present in the
hook; added afterward → not.*

> Caveat to avoid confusion: codex runs the **model's own** shell tool commands
> via `/bin/bash -lc` (a login shell). That login shell applies to the agent's
> tool calls, **not** to hook subprocesses. Do not assume a codex hook gets
> login-shell initialization just because agent commands do.

## Sandbox Interaction (important)

**[observed]** Under `codex exec --sandbox workspace-write`, hook subprocesses
fire (codex reports `hook: <event> Completed`) but their filesystem writes did
not land — repeated runs produced zero output files, even when writing into the
workspace root. The only hook writes that succeeded in testing came from a
codex run with `permission_mode: bypassPermissions` (full access). This
indicates **codex applies its sandbox to hook subprocesses**, not just to the
model's tool calls.

Practical rule: a codex hook running under a restrictive sandbox should not
assume it can write arbitrary paths. Decision output on stdout/stderr and exit
codes still work; side-effect writes to disk may be silently dropped. A
positive-control write under a bypass/full-access run could not be captured in
this environment (the flag is unavailable here), so the exact writable-root
boundary under `workspace-write` is **[unverified]** — treat any hook that must
write files as sandbox-dependent and test it in the target posture.

## stdout / stderr and Exit Codes

Decision semantics (exit `0` allow, exit `2` block, other non-zero = non-blocking
failure) and the accepted stdout JSON shapes are documented in
[`hook-contract.md`](hook-contract.md#codex-pretooluse--permissionrequest).
Codex accepts both the modern `hookSpecificOutput` shape and a legacy
`{"decision": "block"}` shape.

## Codex vs. Claude Differences

| Aspect | Claude Code | Codex CLI |
|---|---|---|
| Hook `$PWD` | `$HOME` | Project/workspace dir (== payload `cwd`) |
| `cwd` in payload | Tool events only (not `SessionStart`/`Stop`) | Every event, including `SessionStart` |
| Env inheritance | Full launching env | Full launching env (same model) |
| Injected vars | `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `AI_AGENT`, … | `CODEX_API_KEY`, `CODEX_MANAGED_BY_NPM`, `CODEX_MANAGED_PACKAGE_ROOT`, … |
| Sandbox applied to hooks | No sandbox (hooks run unrestricted) | **[observed]** Yes — sandbox mode gates hook filesystem writes |
| Login shell for hooks | No | No (but agent tool commands use `/bin/bash -lc`) |
| Enable flag | Hooks always active if configured | Requires `[features] hooks = true` |

The one rule that is safe on both runtimes: **read `cwd` from the stdin payload,
never trust `$PWD`.**

## See Also

- [`hook-environment.md`](hook-environment.md) — the Claude Code runtime environment
- [`hook-contract.md`](hook-contract.md) — exit codes and JSON decision shapes (both runtimes)
- [`hook-taxonomy.md`](hook-taxonomy.md) — how agent-runtime hooks differ from bento lifecycle-extension hook scripts and hook skills
