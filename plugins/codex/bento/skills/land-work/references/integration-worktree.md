# Persistent Integration Worktree

`land-work-create-preview.py` normally materializes each merge candidate in a
fresh scratch worktree under `/tmp` (`git worktree add --detach`), then
removes it once the caller is done. A fresh worktree has no build state — no
Cargo `target/`, no `node_modules`, no incremental TS/Vite caches — so every
landing in a compiled-language repo pays a full cold build at verification
time.

When the repo's `swarm-config.json` declares `landing.integration_worktree`
(see `swarm/references/landing-config.md` for that schema), the preview
script materializes the merge candidate there instead, so build caches
accumulate across landings.

## Behavior

- **Resolution.** `land-work-create-preview.py` resolves
  `landing.integration_worktree` by invoking `swarm-discover.py` (which
  tilde-expands the path) in the checkout it is run from. This only happens
  when the caller did **not** pass an explicit `--preview-dir`; an explicit
  `--preview-dir` always overrides the configured path.
- **First use.** If the configured path is absent, it is created fresh via
  `git worktree add --detach`, exactly like the scratch path.
- **Reuse.** If the path already exists and is a registered worktree of this
  repo with no foreign untracked files, it is reset (`git reset --hard` to the
  leased base) and reused. Tracked modifications left over from this script's
  own prior `--no-commit` merge are not disqualifying — `reset --hard` clears
  them, including any in-progress `MERGE_HEAD` — since nothing in this
  worktree's lifecycle other than this script's own merges ever produces
  them. Ignored paths (a repo's own `target/`, `node_modules/`, etc.) are
  exactly the build caches this feature exists to preserve, and are never
  touched by the reset.
- **Foreign dirt refuses reuse.** An **untracked, non-ignored** file in the
  configured worktree means something else touched it (a person, another
  tool). The script never resets over that: it warns and falls back to a
  fresh scratch `/tmp` directory for this run instead, leaving the
  configured worktree exactly as found.
- **Not a registered worktree.** If the configured path exists but is not a
  worktree of this repo at all, the same fallback applies (with its own
  warning).
- **Merge conflicts.** A conflicting merge against the persistent worktree
  runs `git merge --abort` before reporting the failure, so the worktree is
  left clean for the next landing attempt rather than stuck mid-merge or
  removed outright.
- **Cleanup never removes it.** `--cleanup --preview-dir <path>` is a safe
  no-op (`cleaned_up: false`, `ok: true`, a warning explaining why) when
  `<path>` resolves to the configured `landing.integration_worktree` — the
  whole point of the feature is that it persists across landings. Skip the
  cleanup step in the land-work workflow when the preview payload reports
  `"persistent_worktree": true`.
- **Without the config, nothing changes.** Repos with no
  `landing.integration_worktree` (or no `swarm-config.json` at all) get the
  scratch `/tmp` path, byte-for-byte the same as before this feature existed.

## Output Fields

`land-work-create-preview.py`'s JSON payload adds two fields relevant to this
feature:

| Field                 | Meaning                                                                 |
|-----------------------|--------------------------------------------------------------------------|
| `persistent_worktree` | `true` when `preview_dir` is the configured `landing.integration_worktree` (whether freshly created or reused this run). |
| `reused_worktree`     | `true` only when an existing persistent worktree was reset and reused this run (`false` on first use, and always `false` for a scratch worktree). |

## Scope

This covers serial landings only. Batch assembly (multiple branches merged in
sequence against one persistent worktree, then gated once at the tip) is a
separate concern — see the batched-swarm-landing epic's batch-primitives
issue.

## Known Limitation: Single-Writer Assumption

This feature adds no locking around the persistent worktree: two concurrent
`land-work-create-preview.py` invocations against the same configured
`landing.integration_worktree` (e.g. from two independent sessions landing to
the same repo at once) can race their `git reset --hard` / `git merge`
against the same directory and corrupt each other's preview. This is safe
today only because land-work already has a single-writer invariant in
practice — swarm's Phase 4 serializes all landings through one lead, one
branch at a time — so no documented workflow actually drives two concurrent
land-work runs against one repo. A scratch `/tmp` preview never had this
risk (each invocation got a unique directory); a persistent worktree is a new
shared, stateful resource. Locking belongs with the batch-primitives work
(the batched-swarm-landing epic), which already needs to serialize access to
the same worktree for its assemble/gate/bisect sequence — see bento-nmmk.
