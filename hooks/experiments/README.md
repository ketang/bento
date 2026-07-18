# Hook Environment Experiments

Runnable probe scripts that produce labelled output demonstrating the claims in
[`../references/hook-environment.md`](../references/hook-environment.md).

Each script is a self-contained Claude Code hook. Wire it, start a new session,
trigger the relevant event, then read the output file. The output is written
with explicit `CLAIM`, `EXPECTATION`, and `RESULT` labels so you can verify
each assertion independently.

## Prerequisites

- Claude Code installed and accessible as `claude`
- This repo cloned locally (scripts must be executed from absolute paths)
- `jq` and `python3` on PATH (used inside the scripts)
- Read/write access to `/tmp`

Set a shell variable for convenience:

```bash
BENTO=/path/to/this/repo   # your local clone
```

Make the scripts executable:

```bash
chmod +x $BENTO/hooks/experiments/probe-env.sh
chmod +x $BENTO/hooks/experiments/probe-stdin.sh
chmod +x $BENTO/hooks/experiments/probe-stdout.sh
```

---

## Experiment 1 — Environment variable inheritance and working directory

**Script:** `probe-env.sh`  
**Hook type:** `PostToolUse` / `Bash`  
**Output file:** `/tmp/hook-probe-env.txt`

**What it tests:**

| Claim | How verified |
|---|---|
| Hooks inherit user-defined vars (`DOTFILES`, `NVM_DIR`, etc.) | Prints each var; absent = claim false |
| Hooks see Claude-injected vars (`CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, etc.) | Printed in section 2; absent = claim false |
| Plugin bin dirs are prepended to PATH | Section 5 splits PATH; plugin entries listed separately |
| Hook PWD is `$HOME`, not the project dir | Section 6 compares `$PWD` to payload `cwd` field |
| No file descriptor is a TTY | Section 7 tests `[ -t 0/1/2 ]` |

**Steps:**

1. Add to `~/.claude/settings.json`:

```json
"hooks": {
  "PostToolUse": [
    {
      "matcher": "Bash",
      "hooks": [{ "type": "command",
                  "command": "/PATH/TO/BENTO/hooks/experiments/probe-env.sh" }]
    }
  ]
}
```

2. Start a **new** Claude session (settings are read once at startup):

```bash
claude
```

3. Run any trivial Bash command to fire the hook:

```
echo trigger
```

4. Read the output file from a separate terminal:

```bash
cat /tmp/hook-probe-env.txt
```

**Key things to look for in the output:**

```
=== 2. CLAUDE-INJECTED VARIABLES ===
  CLAUDECODE:                    1
  AI_AGENT:                      claude-code_<version>_agent
  CLAUDE_CODE_SESSION_ID:        <uuid>
  CLAUDE_CODE_TMPDIR:            /tmp/claude-<uid>

=== 3. USER-DEFINED VARIABLES ===
  DOTFILES:                      /home/<user>/dotfiles   ← inherited from parent
  NVM_DIR:                       /home/<user>/.nvm       ← set but shim not in PATH

=== 5. PATH ANALYSIS ===
  Plugin-injected PATH entries:
    /home/<user>/.claude/plugins/cache/bento/bento/<ver>/bin
    ...

=== 6. WORKING DIRECTORY vs PAYLOAD cwd ===
  Hook PWD ($PWD):               /home/<user>            ← $HOME, not project
  Payload cwd field:             /home/<user>/project/x  ← actual project dir
  VERDICT (cwd):                 CONFIRMED — PWD is $HOME, not project dir

=== 7. TTY STATUS ===
  stdin is TTY:   no
  stdout is TTY:  no
  stderr is TTY:  no
```

---

## Experiment 2 — stdin payload shape per event type

**Script:** `probe-stdin.sh`  
**Hook types:** `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`  
**Output files:** `/tmp/hook-probe-stdin-<EVENT>.txt`

**What it tests:**

The documented stdin payload shapes in `hook-environment.md` — which fields
appear for each event type and what they contain.

**Steps:**

1. Add one or more entries from `settings-snippet.json` to `~/.claude/settings.json`.
   Each entry sets `PROBE_EVENT=<name>` so outputs land in separate files.

2. Start a **new** Claude session:

```bash
claude
```

3. Trigger each event:

| Event | How to trigger |
|---|---|
| `SessionStart` | Starting Claude (fires automatically) |
| `PreToolUse_Bash` | Run any Bash command: `echo hi` |
| `PostToolUse_Bash` | Same as above (PostToolUse fires after) |
| `PreToolUse_Edit` | Ask Claude to edit any file |
| `Stop` | End the session: `/exit` or Ctrl-D |

4. Read each output file:

```bash
cat /tmp/hook-probe-stdin-SessionStart.txt
cat /tmp/hook-probe-stdin-PreToolUse_Bash.txt
cat /tmp/hook-probe-stdin-PostToolUse_Bash.txt
cat /tmp/hook-probe-stdin-Stop.txt
```

**Key things to look for:**

```
# SessionStart — no cwd, no tool_name
  'session_id'   = "<uuid>"   ← UUID — same across all hooks in one Claude session
  'transcript_path' = "/path/to/transcript.jsonl"

# PreToolUse/Bash — has cwd and tool_input
  'tool_name'    = "Bash"
  'tool_input'   = {"command": "echo hi"}
  'cwd'          = "/home/<user>/project/x"  ← project dir, NOT hook PWD
  'session_id'   = "<same uuid as SessionStart>"

# PostToolUse/Bash — adds tool_response
  'tool_response' = {"output": "hi\n", "exit_code": 0}

# Stop — no cwd, has stop_hook_active flag
  'stop_hook_active' = false
  'transcript_path'  = "/path/to/transcript.jsonl"
```

---

## Experiment 3 — stdout and stderr routing

**Script:** `probe-stdout.sh`  
**Hook type:** `PreToolUse` or `PostToolUse` / `Bash`

**Run each mode in isolation** (the block mode returns exit 2, which stops
subsequent hooks in the same group).

### Mode A — non-JSON stdout is discarded

```json
"PostToolUse": [
  { "matcher": "Bash",
    "hooks": [{ "type": "command",
                "command": "MODE=noise /PATH/TO/BENTO/hooks/experiments/probe-stdout.sh" }] }
]
```

Trigger: `echo anything`

**Expected result:** Claude's reply does not contain the marker text written to
stdout. If it appears, the "stdout is discarded" claim is false.

Log written to `/tmp/hook-probe-stdout-noise.txt`.

### Mode B — hookSpecificOutput JSON is interpreted

```json
"PreToolUse": [
  { "matcher": "Bash",
    "hooks": [{ "type": "command",
                "command": "MODE=json_allow /PATH/TO/BENTO/hooks/experiments/probe-stdout.sh" }] }
]
```

Trigger: any Bash command that would normally require a permission prompt.

**Expected result:** the command runs without a permission dialog. The JSON
emitted to stdout was interpreted as an allow decision.

Log written to `/tmp/hook-probe-stdout-json_allow.txt`.

### Mode C — stderr is surfaced on block (exit 2)

```json
"PreToolUse": [
  { "matcher": "Bash",
    "hooks": [{ "type": "command",
                "command": "MODE=stderr_on_block /PATH/TO/BENTO/hooks/experiments/probe-stdout.sh" }] }
]
```

Trigger: any Bash command.

**Expected result:** Claude's denial message contains or quotes the text
`BLOCK REASON: probe-stdout experiment`. If it does not appear, the
"stderr is surfaced on block" claim is false.

Log written to `/tmp/hook-probe-stdout-stderr_on_block.txt`.

---

## Experiment 4 — Codex CLI hook environment (real `codex exec` run)

**Script:** `codex-probe.sh`
**Runtime:** Codex CLI (`codex-cli 0.144.1`)
**Captured evidence:** `codex-hook-capture-verified.txt`

Unlike experiments 1–3 (Claude Code), this probe targets **Codex** and produced
the evidence behind [`../references/codex-hook-environment.md`](../references/codex-hook-environment.md).

**What it tests:** codex hook working directory, stdin payload shape per event,
environment-variable inheritance (including transitive inheritance of an
ancestor process's custom vars), codex-injected vars, login-shell/TTY status.

**Steps:**

1. Ensure `[features] hooks = true` in `~/.codex/config.toml`.
2. Back up `~/.codex/hooks.json`, then add the probe to `SessionStart`,
   `PreToolUse`, and `PostToolUse` (pass the output path inline so the script
   knows where to write):

```json
{ "hooks": [ { "type": "command",
  "command": "SP_OUT=/tmp/codex-probe-out.txt /PATH/TO/BENTO/hooks/experiments/codex-probe.sh" } ] }
```

3. Trigger a real run from a writable workspace:

```bash
export CUSTOM_PROBE_VAR=probe-value
codex exec -c 'model_reasoning_effort="low"' "Run exactly this and nothing else: echo marker"
```

4. Read `/tmp/codex-probe-out.txt` and **restore the original `~/.codex/hooks.json`.**

**Key things to look for** (see the committed capture for a full example):

```
"cwd":"<workspace>", "hook_event_name":"SessionStart", "permission_mode":"..."
PWD=<workspace>          ← equals cwd, NOT $HOME (opposite of Claude)
CUSTOM_PROBE_VAR=...     ← custom var inherited from the launching env
CLAUDECODE=1             ← in the capture: transitively inherited from an
AI_AGENT=claude-code_... ← ancestor Claude session that launched codex
CODEX_API_KEY / CODEX_MANAGED_BY_NPM / CODEX_MANAGED_PACKAGE_ROOT  ← codex-injected
login_shell: no          ← hook is not a login shell
```

**Sandbox caveat (observed):** under `--sandbox workspace-write`, hooks fire but
their filesystem writes may not land — see the reference doc's *Sandbox
Interaction* section. The committed capture came from a full-access
(`permission_mode: bypassPermissions`) run.

---

## Reading the original evidence

The conclusions in `hook-environment.md` were reached before these scripts
existed, using three pieces of direct evidence gathered in a live session:

1. **`/proc/$$/environ` dump** — The Bash tool subprocess (same launch model as
   hooks) was asked to print its own `/proc/PID/environ`. It showed `DOTFILES`,
   `TMUX`, `NVM_DIR`, `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, and plugin PATH
   entries. Transcript: `~/.claude/projects/*/transcripts/`.

2. **`/tmp/tmc-debug.txt`** — A SessionStart hook containing
   `printenv | grep TMC >> /tmp/tmc-debug.txt` was already wired in
   `~/.claude/settings.json`. The file showed `TMC_AGENT_LAUNCH_ID`,
   `TMC_AGENT_TRACK`, etc., proving hooks see session-specific env vars set
   before Claude launched.

3. **Live hook command expansion** — The command string
   `"cat | $DOTFILES/claude/tmux-state.sh session-start"` in
   `~/.claude/settings.json` requires `$DOTFILES` to expand correctly at hook
   spawn time. Since that hook functioned, the variable was present in the hook
   environment.

These probe scripts make each piece of evidence independently reproducible
from a clean state.
