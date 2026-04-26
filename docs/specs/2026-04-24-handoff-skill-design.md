# /handoff Skill — Design

- Date: 2026-04-24
- Status: Approved (ready for implementation planning in a new session)
- Audience: implementer of the bento `/handoff` skill
- Companion spec: [docs/specs/2026-04-24-agent-plugins-convention-design.md](2026-04-24-agent-plugins-convention-design.md)

## Summary

`/handoff` is a bento skill that generates a prompt to reboot a fresh session on the current work. It writes a markdown file under `/tmp/` with seven structured slots plus free-form notes, then echoes the file contents to chat.

The skill is the first concrete consumer of the `agent-plugins` convention: its on-disk template can be overridden at repo and home scopes per the convention's lookup rules.

## Purpose

In scope:

- **Context-window pressure.** The current session is approaching compaction or exhaustion and the user wants a crisp reboot prompt before in-flight reasoning becomes lossy.
- **Delegation to a teammate.** The user is handing remaining work to a different session, role, or person.
- **General-purpose user-initiated use.** The user invokes `/handoff` whenever they want a continuation prompt; the skill makes no assumption about the trigger.

Out of scope:

- Calendar-style "pick up next week" resumption. `/handoff` is not designed for state that must survive long idle gaps.
- Subagent dispatch (the skill does not feed the prompt to the Agent tool; the user copies or reads the file).
- `claude --resume` integration or session-file emission.
- Writing or refreshing the expedition skill's own `docs/expeditions/<name>/handoff.md`. When an expedition is active, `/handoff` defers to expedition's own session-end protocol.

## Preconditions and Short-Circuit Behavior

The skill operates only when all three preconditions hold:

1. The current working directory is inside a git repository.
2. HEAD resolves to a named branch (not detached).
3. No active expedition is detected in the current worktree.

When any precondition fails, the skill emits a one-line diagnostic and exits with a non-zero code. It MUST NOT write a file in any failure case.

| Failure | One-line message form |
| --- | --- |
| Not in a git repo | `/handoff: not in a git repository; refusing to write a handoff file.` |
| Detached HEAD | `/handoff: HEAD is detached; refusing to write a handoff file. Check out a named branch.` |
| Active expedition | `/handoff: active expedition <name> detected; use the expedition skill's session-end protocol instead (update docs/expeditions/<name>/handoff.md via expedition/scripts/expedition.py).` |

Expedition detection runs `expedition/scripts/expedition.py discover` and treats the current worktree as expedition-active when the discover output places the current worktree at any expedition's base or active task worktree. The discover helper is the authoritative source of truth.

## Output Contract

On success, the skill:

1. Resolves the template (see "Customization") and produces the filled-in markdown content.
2. Writes the content to a fresh path under `/tmp/`.
3. Prints the full contents of the file to chat in the same response, along with the absolute file path.

Filename:

```
/tmp/handoff-<suffix>-<YYYYMMDD-HHMMSS>.md
```

`<suffix>` is determined as follows:

- If the current branch is not the repository's primary branch, `<suffix>` is the current branch name, with `/` replaced by `-` and any character outside `[A-Za-z0-9._-]` replaced by `-`.
- If the current branch IS the primary branch, `<suffix>` is a slug derived by the agent from the handoff contents (typically a 2–4 word kebab-case summary of the work).

Primary-branch detection follows the same approach as the bento `launch-work` skill (consulting `git symbolic-ref refs/remotes/origin/HEAD` first, falling back to local refs).

`<YYYYMMDD-HHMMSS>` is the local-time timestamp at file-write time, zero-padded.

There is no chat-only mode. There is no pre-write approval step. Users edit the resulting file post-hoc if they spot something to fix.

## Template

The template is a markdown skeleton with seven labeled slot headings, in this fixed order:

1. **Next action** — the single concrete next step for the new session, at the top so a fresh agent sees it first.
2. **Original task** — the user's request that started this session, in one line.
3. **Branch & worktree** — current branch, worktree path, primary branch.
4. **Verification state** — what was run, what passed, what failed, and what was not yet tested.
5. **Decisions & dead-ends** — non-obvious choices made, approaches ruled out and why.
6. **Pending decisions / blockers** — questions waiting on the user, external blockers.
7. **Notes** — free-form prose for in-flight reasoning that doesn't fit a slot.

At runtime the agent writes the body text under each heading; the helper does not perform `{{token}}` substitution. The on-disk template is editable as ordinary markdown; users may rewrite or extend it within their own override (see "Customization"). The seven-slot structure describes the bundled default; a user override may add, remove, rename, or reorder headings, and the agent's runtime job remains to write content under whatever headings the resolved template provides.

The bundled default template is shipped at `<skill-dir>/references/templates/handoff.md` and contains:

- The seven headings above, in order.
- A short HTML comment under each heading describing what the agent should write there. (HTML comments survive markdown rendering as invisible guides.)
- No body text outside comments.

## Customization (via the agent-plugins Convention)

`/handoff` resolves its template through the `agent-plugins` convention. The skill identifies as marketplace `bento`, plugin `bento`, and uses `handoff/template.md` as the relative path under that prefix.

Lookup order (file-level, first match wins):

1. `<repo-root>/.agent-plugins/bento/bento/handoff/template.md`
2. `$XDG_CONFIG_HOME/agent-plugins/bento/bento/handoff/template.md` (default `~/.config/agent-plugins/bento/bento/handoff/template.md` when `XDG_CONFIG_HOME` is unset)
3. Plugin-bundled default at `<skill-dir>/references/templates/handoff.md`.

The helper MUST honor `XDG_CONFIG_HOME` per the convention spec. Repo-root determination uses the agent runtime's project-root signal when available, otherwise the nearest ancestor directory containing a `.git` entry (consistent with the convention spec's SHOULD).

## Seeding the Home-Scope Template

The home-scope template is seeded from the bundled default by three independent mechanisms. All three are idempotent: a stat-and-skip when the file already exists.

### Bento Claude plugin SessionStart hook

Add `hooks/scripts/seed-agent-plugins.py` in the bento Claude plugin source, and register it as a `SessionStart` hook in the plugin's `hooks/hooks.json`. The script:

- Resolves the home-scope path: `${XDG_CONFIG_HOME:-$HOME/.config}/agent-plugins/bento/bento/handoff/template.md`.
- If the path exists, exits successfully with no action.
- Otherwise creates the parent directory and copies the bundled default from the plugin's installed handoff skill location.
- Emits no output on success and no fatal error on permission failures (a session that cannot write to the user's config dir should not be blocked from starting).

The hook is implemented as its own script, not as an extension of the existing `auto-allow.py`, so each hook remains single-purpose.

### Codex installer step

`install/_codex-installer-lib.sh` gains a seeding step that runs after plugin bundles are placed. The step:

- For the home installer (`install/codex-home.sh`): creates `${XDG_CONFIG_HOME:-$HOME/.config}/agent-plugins/bento/bento/handoff/` and copies `template.md` from the freshly-installed plugin bundle if and only if the destination is missing.
- For the project installer (`install/codex-project.sh`): creates `<install-root>/.agent-plugins/bento/bento/handoff/` and copies `template.md` if missing. (Project-scope auto-creation is a UX nicety; the convention itself never requires repo-scope auto-creation.)
- Backs nothing up; never overwrites an existing destination file.

### Skill-helper self-heal

`scripts/handoff.py` checks the home-scope path on every invocation. If the file is missing, the helper:

- Creates the parent directory.
- Copies the bundled default into the home-scope path.
- Continues with the requested run.

Self-heal is the belt-and-braces fallback for users who installed bento by some path that runs neither the SessionStart hook nor the Codex installer. The repo-scope file is NEVER auto-created by any mechanism; users opt in by placing it themselves.

## Skill Layout

Canonical source under `catalog/skills/handoff/`:

```
catalog/skills/handoff/
  SKILL.md
  scripts/
    handoff.py
  references/
    templates/
      handoff.md
```

### SKILL.md

Prose contract for the agent. Frontmatter includes `name: handoff`, a one-line description, and `recommended_model: high`. Body covers:

- A short `## Model Guidance` section noting `high` and a one-sentence rationale (distillation of conversation state to a crisp next-action is the load-bearing task).
- Inputs and triggers.
- Preconditions and short-circuit behavior, mirroring this spec's "Preconditions" section but written for runtime use.
- The seven-slot template structure with one-sentence guidance per slot for what the agent should write.
- How to invoke `scripts/handoff.py` and what it returns.
- The expectation that the skill echoes the file contents in chat after writing.
- A "Non-Negotiable Rules" section listing: do not write a file when preconditions fail; do not invent a branch name when on detached HEAD; do not duplicate or replace the expedition handoff document; do not perform `{{token}}` substitution.

Token tightness: the project CLAUDE.md notes skills are injected into the agent's runtime context, so the SKILL.md MUST be terse. Aim for under ~250 lines total including frontmatter.

### scripts/handoff.py

A Python 3 script (matching bento's existing helper style; cf. `expedition.py`, `launch-work-bootstrap.py`). Responsibilities:

- Parse CLI arguments. Suggested interface:
  - `--input <path>` to read filled-in template content from a file.
  - `--input -` to read content from stdin.
  - `--slug <slug>` to override the suffix when the script cannot derive a branch name (i.e., on the primary branch). The agent supplies this when applicable.
  - `-h`/`--help` and `-v`/`--verbose` per the user's global script convention.
- Run preconditions:
  - Verify cwd is inside a git work tree (`git rev-parse --is-inside-work-tree`).
  - Verify HEAD is a symbolic ref (`git symbolic-ref --quiet HEAD`).
  - Run expedition discovery and check the current worktree against the result.
  - On any failure, print the matching diagnostic to stderr and exit non-zero. Do not write a file.
- Detect the primary branch (same approach as `launch-work`).
- Compose the suffix:
  - If current branch is not the primary branch, sanitize the branch name as described in "Output Contract".
  - Otherwise, require `--slug` (the agent supplies it); fail with a clear error if `--slug` is missing.
- Resolve the template via the agent-plugins lookup chain.
- Self-heal the home-scope path if missing.
- Generate the timestamped output path.
- Write the supplied content to that path. (The script does NOT call back into the template; the agent has already produced the filled-in content. The script's job for write is "write these bytes to this path.")
- Print the resulting path to stdout.

The script MUST be invoked by path (matching bento's existing helper convention) so that approvals stay scoped to the script.

### references/templates/handoff.md

The bundled default. A small markdown file with seven headings and one HTML comment per heading. Total length under ~30 lines.

## Bento Claude Plugin: SessionStart Hook Wiring

The Claude plugin's `hooks/hooks.json` already registers `PreToolUse` for `auto-allow.py`. The plan adds a `SessionStart` array and registers the new seeding script:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/auto-allow.py bento ${CLAUDE_PLUGIN_ROOT}" }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/seed-agent-plugins.py" }
        ]
      }
    ]
  }
}
```

The hook source must be wired into the build process so that `scripts/build-plugins` copies it into the generated `plugins/claude/bento/hooks/`. Verify during implementation that the build script picks up new files in the bento Claude plugin's hooks directory; if it does not, the build script itself needs an update.

Codex does not have an equivalent plugin-side hook in this repo's structure. Codex seeding happens through the installer step instead.

## Codex Installer Change

`install/_codex-installer-lib.sh` is the shared library invoked by both `codex-home.sh` and `codex-project.sh`. The plan adds a function and a call site that:

- Determines the seeding root from `BENTO_INSTALL_SCOPE`:
  - `home` → `${XDG_CONFIG_HOME:-$HOME/.config}/agent-plugins/`
  - `project` → `${BENTO_INSTALL_ROOT}/.agent-plugins/`
- For the bento plugin only (not trackers, stacks, or session-id, which do not currently expose customization files), creates `<root>/bento/bento/handoff/` and copies the freshly-installed plugin's bundled `template.md` if the destination does not exist.
- Logs the action through the existing `log()` helper.

The seeding step runs after `plugins[]` placement and before marketplace metadata generation, so it sees the final installed location of the plugin's bundled template.

## Tests

Add `tests/test_handoff.py` to the existing bento test directory (which uses stdlib `unittest`, run via `python3 -m unittest discover -s tests -t .` as part of `scripts/build-plugins`).

Test classes / cases:

### `TestHandoffPreconditions`
- Outside a git repo: helper exits non-zero with the not-in-repo diagnostic and writes nothing.
- Detached HEAD (test fixture creates a temp repo, checks out a commit by SHA): helper exits non-zero with the detached-HEAD diagnostic.
- Active expedition (mock `expedition.py discover` output to claim the cwd is an expedition worktree): helper exits non-zero with the expedition pointer.
- All preconditions pass: helper proceeds.

### `TestSuffixDerivation`
- Non-primary branch with a clean name (`feat-foo`): suffix is `feat-foo`.
- Non-primary branch with a slash (`user/feature`): suffix is `user-feature`.
- Non-primary branch with unusual characters: sanitized.
- Primary branch (`main`): helper requires `--slug` and uses it.
- Primary branch with `--slug` missing: helper exits non-zero.

### `TestTemplateResolution`
- Repo-scope template present: helper uses it (covers any home-scope or bundled default in the same fixture).
- Repo-scope absent, home-scope present: helper uses home-scope.
- Both overrides absent, bundled default present: helper uses the bundle.
- `XDG_CONFIG_HOME` set: home-scope is computed from it, not from `~/.config`.
- `XDG_CONFIG_HOME` unset: home-scope falls back to `~/.config`.

### `TestSelfHeal`
- Home-scope template absent before run: present after run, contents match the bundle.
- Home-scope template already present and differs from bundle: helper leaves it untouched.

### `TestPathGeneration`
- Output path matches the expected pattern with a frozen mock of "now" to assert the timestamp format.
- Two consecutive runs produce two distinct timestamped files.

### `TestSeedHook`
- `hooks/scripts/seed-agent-plugins.py` run twice in a row: second run is a no-op (file mtime unchanged); first run created the file.
- Run with the home-scope file already present: the script does not modify it.

Tests use `tempfile.TemporaryDirectory` for git fixtures and isolate `XDG_CONFIG_HOME` and `HOME` per test where needed. They do not depend on the developer's actual home directory.

## Build Integration and Version Bumping

Per `AGENTS.md`: "Every time you modify `catalog/skills/` or `scripts/build-plugins`, evaluate whether a version bump is warranted." This implementation:

- Adds a new skill under `catalog/skills/handoff/` → behavioral change → version bump required.
- Adds a new hook script under the bento Claude plugin → behavioral change → version bump required.
- Modifies `install/_codex-installer-lib.sh` → not under `catalog/skills/` or `scripts/build-plugins`, but ships in installable artifacts; consider whether it counts. Conservative answer: this counts as part of the bento plugin's behavior and warrants a bump alongside the other changes.

The bump uses `scripts/bump-plugin-versions` as documented; do not edit `catalog/plugin-versions.json` by hand.

After bumping, run `scripts/build-plugins` so the regenerated manifests pick up the new versions; commit the regenerated outputs together with the version bump.

## Open Items / Explicit Non-Decisions

The following are explicitly NOT decided in this spec and are left to the implementer's judgment during planning or implementation:

- **Whether `handoff.py` reads its content from stdin or from `--input <path>` first by default.** Either is fine; the spec only requires both to work.
- **The exact wording inside `references/templates/handoff.md`.** Provided the seven headings appear in order and each carries a brief HTML-comment hint, the wording is editorial.
- **Slug derivation for the primary-branch case.** The agent generates the slug; the helper just consumes `--slug`. The spec does not prescribe slug-derivation rules beyond "kebab-case, 2–4 words".
- **Whether the SessionStart hook also seeds future bento skills' agent-plugins directories.** v1 is bento/handoff-only. If other bento skills adopt the convention later, the hook's coverage can expand then.

## Non-Negotiable Rules (for the runtime)

These are repeated in `SKILL.md` so the runtime agent sees them:

- Do not write a file when preconditions fail.
- Do not invent a branch name when HEAD is detached.
- Do not duplicate or replace expedition's `handoff.md` when an expedition is active.
- Do not perform `{{token}}` substitution on the template; write prose under each heading.
- Do not modify a repo-scope or home-scope user-edited template; treat both as read-only.
- Do not chat-only the output. Always write the file when preconditions pass.

## References

- The companion `agent-plugins` convention spec: [docs/specs/2026-04-24-agent-plugins-convention-design.md](2026-04-24-agent-plugins-convention-design.md).
- Existing bento helpers used as implementation references for style and primary-branch detection: `catalog/skills/launch-work/scripts/launch-work-bootstrap.py`, `catalog/skills/expedition/scripts/expedition.py`.
- Existing hook example to model the new SessionStart hook against: `plugins/claude/session-id/hooks/`.
- The Codex installer to extend: `install/_codex-installer-lib.sh`.
