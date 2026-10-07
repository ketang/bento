# Guidance audit: what model progress made unnecessary or counterproductive

Date: 2026-10-07. Scope: every file under `catalog/skills/`, top-level agent
docs (CLAUDE.md, AGENTS.md, README, DESIGN, hooks), `catalog/hooks/`, and
`docs/`. Report only — nothing was changed.

Rubric:
- **A — scaffolding for old weaknesses.** Shouting, restating rules,
  anti-laziness tables, micro-procedures for things models do natively.
- **B — duplicates the harness.** Todo lists, subagents, worktrees,
  compaction, memory, review.
- **C — counterproductive now.** Language current models over-apply, stale
  or contradictory text, runtime quirks that may no longer exist, token load.
- **K — keep.** Repo facts, contracts, safety rails, deterministic scripts.

## Headline

Bento's *mechanisms* are still sound: the scripts, the hook guards, the
contracts and the safety rails on landing and deletion. The *prose around*
those mechanisms was written for models that skipped steps, stopped early and
needed every rule said five times. Current models follow instructions
literally and precisely. For them that prose is now mostly cost, and in places
it causes harm: emphatic absolutes get over-applied. Roughly **40–50% of skill
prose can be removed** without losing any of the safety guarantees. The
deterministic scripts already enforce most of what the prose shouts.

## Cross-cutting patterns (highest leverage)

| # | Pattern | Where | Cat | Recommendation |
|---|---|---|---|---|
| 1 | **"Hard trigger — always invoke… Never skip…" descriptions** | launch-work, land-work, cross-check, issue-readiness-check (`SKILL.md:3`) | C | Literal-minded models fire these on trivial edits and plans, and cross-check then pauses for the operator. Rewrite as calm triggers, with the trivial-work exemption next to the trigger. launch-work's "reload it late in a task" is a pre-compaction workaround: drop it. The main-branch PreToolUse guard already enforces worktrees mechanically. |
| 2 | **Anti-Rationalization tables** ("excuse → counter") | land-work (13 rows, ~700 words), launch-work, swarm, closure | A | Written for a corner-cutting model. Nearly every row restates a rule the scripts now enforce. Delete them. At most keep 2–3 pure-judgment lines: red base, silence ≠ approval, waiver timing. |
| 3 | **Non-Negotiable Rules lists that restate the Workflow** | land-work (17 bullets), launch-work (14), handoff, bentobug, closure | A | One statement per rule. Workflow steps don't need a second, all-caps copy. |
| 4 | **Same rule restated 3–7×** | land-work preview cleanup (5×) and verifier status (3×); closure eligibility (7×) and "not for your own work" (6×); beads "close only after landing" (6×); swarm verify gate (5×); audit "secrets never optional" (3×) | A/C | Repetition used to be emphasis. Now it costs tokens, and it forces carve-out paragraphs whenever a repeated absolute has a documented exception. |
| 5 | **"Model Guidance: Recommended model: high… degrades on smaller models"** | 13 SKILL.md files | C | The model can't act on this. `recommended_model` frontmatter is used by 0 of 21 skills, but README/DESIGN still document it. Delete the prose and the documented convention, or re-adopt it deliberately in `metadata.json`. |
| 6 | **Manual fallback flows loaded on every run** | land-work manual compare-and-set (~1.8k words, `SKILL.md:311–459`); land-work and swarm Batch sections (~1.5k words each) that only `landing.mode: batch` repos use | C | Move to references loaded on demand. The `land.py` path already says "re-run, don't fall back". |
| 7 | **Hand-written reviewer prompts and fan-out instructions** | land-work fallback reviewer (`SKILL.md:181–248`); code-bloat-sniffer's dependency on `superpowers:dispatching-parallel-agents`; swarm triage micro-steps | B | Use the native `/code-review` and subagents. Keep what is bento-specific: reviewer independence from session context, merge-base range, cross-runtime review in cross-check. |
| 8 | **Micro-procedures for native skills** | `gh`/`bd` command cheat-sheets (github-issue-flow, beads-issue-flow), lockfile→installer table (launch-work), grep recipes (code-bloat-sniffer, audit), textbook code-smell definitions and per-tool CLI tutorials (audit `quality-standards.md`, `static-analysis-tools.md`), TDD/commit-at-checkpoint advice, "narrate findings progressively" | A | Cut to *what to look for, what evidence to give, and the non-obvious exceptions*. |
| 9 | **Runtime-quirk workarounds — check before keeping** | land-work and closure `CLAUDE.md` ("Unhandled node type" ban on compound shell commands; the blanket ban also slows read-only work, and land-work's own snippets use `$(...)`); Codex "no pipelines for sandbox approvals"; issue-readiness-check's assumption that Codex needs user permission to delegate; swarm "workers stall even under bypassPermissions"; audit's doubled-path warning; cross-check CLI flags (`claude -p --tools`, `codex exec --sandbox`) | C (verify) | Reproduce each quirk on the current runtimes. Delete the ones that no longer reproduce. |
| 10 | **Rigid pass/fail thresholds** | audit `quality-standards.md` (function >25 lines, >3 returns, any undocumented export = warning); "any CVE → error regardless" | C | Current models apply these literally and flood reports. Make them signals that call for judgment, with downgrades backed by stated evidence. Keep "race = error". |
| 11 | **Issue-ID provenance in instructions** ("(bento-rdtn.14)", "bento-nmmk") | land-work, hooks/README, integration-worktree.md | A | Noise to the agent. git history already holds it. |

## Always-loaded repo guidance (CLAUDE.md + AGENTS.md, ~2.8k tokens/turn)

| Finding | Cat | Recommendation |
|---|---|---|
| **Three conflicting todo rules.** CLAUDE.md:26 bans TodoWrite/TaskCreate, CLAUDE.md:58–66 adds a carve-out to undo that, and the AGENTS.md Codex block only bans markdown TODOs. | B/C | One line: "Durable items go in `bd`; in-session checklists may use the harness todo tool." Delete the carve-out. |
| **"Session Completion" block**: MANDATORY/CRITICAL/NEVER ×6, "YOU must push", "retry until it succeeds", "clear stashes, prune remote branches", `git pull --rebase` | A/C | The `check-unpushed` Stop hook already enforces this. "Clear stashes/prune" is a destructive step with no judgment that overlaps `closure`. Modern models will over-apply it, for example pushing from subagents. Collapse to 2 lines and drop the destructive step. |
| **RTK block** ("always prefix with `rtk`", ~40-line cheat-sheet) | C | `rtk` isn't installed in cloud sessions, so every prefixed command fails. The block also steers the model away from the native Read/Grep tools. Move it to user-global config, or make it one conditional line. |
| **Beads described 3×** (two generated blocks plus a hand-written one; `rtk bd` vs `bd`) | A | One short section. `bd prime` carries the detail. |
| Hard-coded `/home/ketan/project/bento` primary checkout | C | Say "first entry of `git worktree list`". |
| Content-hash patch-bump explained 4× (AGENTS, DESIGN, README, version-bump.md) | A | One line plus a pointer. |
| "Safe editing guidance" and "Typical maintenance workflow" restate "Rules for agents" | A | Merge. |
| Home-scope path contradiction: AGENTS/DESIGN say `~/.config/agent-plugins`, the spec and `extensions.md` say macOS uses `~/Library/Application Support` | C | Fix to match the spec. |

## Docs

- **`docs/plans/` (8 files) and `docs/specs/*-plan.md`**: 430 unchecked
  `- [ ]` boxes for work that has shipped. Each opens with "REQUIRED SUB-SKILL:
  Use superpowers:…". An agent that opens one may treat it as pending work or
  follow its directives. **Retire them; git history keeps them.**
- Superseded specs still marked current: `2026-04-04-auto-version-bump-design`
  (it describes the removed manual bump), and `compress-docs-design` is still
  "draft". Mark them superseded or delete them.
- Stale references: README promises "separate hook wiring", which is no longer
  needed. DESIGN calls the repo both "Private marketplace" and "public repo",
  and its skill table lists 10 of 21 skills.
- `docs/stories/INDEX.md` is missing `code-bloat-sniffer`. Several stories
  quote old SKILL.md text: the launch-work description, swarm "one branch at a
  time", the handoff template slots. Wording in
  `compress-docs-token-reduction.md:16` is inverted. **Any slimming must update
  the stories' Auditable Claims and regenerate INDEX.md.**
- `ERRORS.md` is empty, and `project-memory` contradicts CLAUDE.md, which says
  to use `bd remember` and not memory files.

## Per-skill verdicts

| Skill | Verdict | ~Removable | Key notes |
|---|---|---|---|
| land-work | SLIM | 55% of prose (SKILL.md 6.7k → ~2.5k words) | Move the manual flow and Batch section to references. Delete the anti-rationalization table. Resolve the contradiction between step 6a's gate-on-exact-preview and `land.py`'s no-pause flow by stating that the verifier manifest *is* the gate. `integration-worktree.md` scope and lock text is stale. Merge `direct-primary-branch.md`. |
| launch-work | SLIM | 45% | Calm the trigger. The expedition-precedence block exists in 3 copies; keep it in expedition. Move the `.claude/settings*.json` symlink procedure (prose duplicated in swarm) into `launch-work-bootstrap.py --apply`. Drop the lockfile table. |
| swarm | SLIM hard | 50% | Native subagents and teams cover the fan-out. Keep triage/overlap scripts, lead-only landing, the landing queue and cross-runtime parity. Delete "use Grep/Glob tools, not shell grep", which is wrong on Codex. `continuation-state.md` silently edits `~/.claude/settings.json`; revisit it. Check that the `TeamCreate` tool names and the hardcoded `model: "sonnet"` are still current. |
| expedition | KEEP, light slim | 20% | Distinct capability: durable in-branch state, numbered task branches, failed experiments preserved. Final Landing step 1 should go through close-task. |
| closure | KEEP, SLIM | 40% | Native worktree tools only clean up the current session. Closure's cross-runtime garbage collection of crashed sessions still matters. Lead the description with a positive trigger. Merge the tracker references. Verify the session-log paths in `closure-scan.py`. |
| audit | KEEP, SLIM | 40% | Repo-wide, not diff-scoped, so not native. Shrink `static-analysis-tools.md` to a severity map. Make the thresholds judgment-based. Keep `control-integrity.md` almost whole. |
| wire-land-verifier | KEEP, SLIM | 30% | Remove the script-internals prose. Keep "never pick silently, even with one candidate". |
| cross-check | KEEP, SLIM | 25% | Cross-runtime review is not native. Calm the trigger. Reduce "Do NOT rubber-stamp" in the prompts to one calm sentence. Verify the CLI flags. |
| build-vs-buy | SLIM | 25% | Keep the build-baseline and incumbent guardrails. The 431-line hand-kept vendor catalog goes stale and keyword matching can anchor on the wrong category; consider a plain manifest dump instead. |
| beads-issue-flow | SLIM heavy | 40% | State the closure rule once. Delete the commands block. Merge the duplicated closure-flag sections. Keep the verified CLI shapes and the precedence note over the Session Completion block. |
| github-issue-flow | SLIM | 35% | Keep the ancestry and `ls-remote` evidence rule; cut the `gh` tutorial. |
| issue-readiness-check | SLIM hard | 45% | "Never skip" is stated about 4×, and Codex asks for permission even on trivial issues. Keep the fresh-context review and the verdict schema. |
| handoff | SLIM | 35% | Its lead use case, context pressure, is now native compaction. Re-center it on cross-session, cross-person and cross-runtime handoff. |
| compress-docs | SLIM + update premise | 40% | Its reason codes can't express "scaffolding for old model weaknesses" or "over-emphatic", which is now the main kind of bloat. Add a code for that. Add Codex global paths. |
| code-bloat-sniffer | KEEP, SLIM | 30% | Drop the superpowers dependency. Check whether ts-prune and the other listed tools are still maintained. |
| bentobug | SLIM | 40% | Keep the script contract; collapse the trigger and rules prose. |
| project-memory | SLIM to ~10 lines or MERGE | 70% | Generic advice that native memory and `bd remember` cover. Conflicts with CLAUDE.md. |
| generate-audit | RETIRE | 80% | Self-declared deprecated. Move its "don't name it `audit`" warning into `audit`. |
| generate-web-demo / maintain-web-demo | KEEP / consider MERGE | 10% / 25% | maintain-web-demo copies the warning-queue contract from generate-web-demo; point to the original instead. |
| dev-skill | KEEP | 15% | Holds facts the model can't know. |
| catalog/hooks | KEEP | — | Quiet when healthy, and they enforce what the prose shouts. `session-id` writes one global `~/.claude/session_id` (concurrent sessions race on it); check whether the harness now exposes the session ID. |

## Must survive any slimming

- All deterministic scripts and hook guards. They are the real enforcement.
- Landing contract: verify the exact merge-preview tree, compare-and-set
  lease, `--no-ff` merges with no squash, a verifier that runs zero checks
  fails, close the tracker only after verified landing (with `merge-base
  --is-ancestor` plus `ls-remote` evidence), worktree removed before branch,
  `branch -d` only, untracked-file accounting, `BENTO_LAND_WORK=1`.
- Closure: liveness tables, "a dirty worktree is not evidence of life",
  `-D` only when `unique_patch_count == 0`, deletion only through helper
  apply modes.
- Facts the model can't know: worktree root, `.agent-mode.local` keys, the
  agent-plugins paths and precedence, the hook extension grammar and exit 75,
  verified `bd` CLI shapes, "invoke scripts by path so approvals stay scoped",
  hooks read `cwd` from stdin, `catalog/` is canonical and `plugins/` is
  generated.
- Swarm: teammates never land or push, and landing config falls back to serial.
- Expedition: its invariants and coordinator-only writes.

## Suggested order of work

1. **Always-loaded guidance** (CLAUDE.md/AGENTS.md): biggest per-turn cost,
   with real contradictions and the broken `rtk` rule.
2. **Trigger descriptions** of the 4 "Hard trigger" skills: these cause
   over-invocation.
3. **land-work, swarm, launch-work** slimming: the largest skills.
4. Retire `docs/plans/` and the superseded specs; retire `generate-audit`.
5. Verify the runtime quirks (pattern 9), then delete the ones that are stale.
6. Remaining skill trims. Update stories and INDEX.md alongside each change.
