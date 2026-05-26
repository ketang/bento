# Design: Stable Symlink Path for require-worktree Hook Registration

**Date:** 2026-05-25  
**Issue:** bento-zew  
**Status:** Approved

## Problem

`register-require-worktree-hook.py` writes the full versioned plugin-cache
path into `~/.claude/settings.json` on every SessionStart:

```
/home/<user>/.claude/plugins/cache/bento/bento/1.0.61/hooks/scripts/require-worktree.sh
```

Two problems with this:

1. **Version churn.** The path embeds the plugin version. Every release
   produces a new path, requiring a stale-entry eviction loop to remove
   the previous version's entry from `settings.json`.
2. **Hardcoded home directory.** The path is absolute from the user's home,
   making it non-portable (though this matters less in practice).

The eviction machinery (`_is_stale_bento_entry`, the `kept` loop in
`register()`) exists solely to handle version churn. It's complexity that
wouldn't be needed with a stable registration target.

## Decision

Use a stable symlink instead of a versioned path.

**Why symlink over copy:**
- A dangling symlink (plugin uninstalled) fails loudly at hook execution time
  ("command not found"), rather than silently running a stale copy.
- The symlink always points at the canonical versioned script; the copy would
  become stale if not refreshed.
- Correct failure mode: when the plugin is gone, the hook should fail visibly.

**Why not `$HOME` env variable expansion in the command string:**
- Solves the hardcoded-home problem but not the version-churn problem.
- The eviction loop and path-update machinery would still be required.

## Architecture

### Stable symlink location

```
$HOME/.claude/hooks/bento/require-worktree.sh
  → <versioned-plugin-root>/hooks/scripts/require-worktree.sh
```

This location is owned by `register-require-worktree-hook.py`. Any
pre-existing file or symlink at this path is overwritten unconditionally.

### SessionStart hook behavior

On every SessionStart, `register-require-worktree-hook.py`:

1. **Creates the directory** `$HOME/.claude/hooks/bento/` with `mkdir -p`
   (mode from umask; no special permissions required).
2. **Updates the symlink** atomically:
   - `os.symlink(target, tmp_path)` to a temp file in the same directory.
   - `os.replace(tmp_path, stable_path)` — atomic on POSIX; concurrent
     sessions never observe a missing or broken link mid-update.
3. **Registers the stable path** in `settings.json` via the existing
   `_atomic_write_json()` (tempfile + `os.replace()`). Concurrent sessions
   writing the same idempotent stable path are safe.

### Failure modes

| Condition | Behavior |
|---|---|
| Plugin cache purged / uninstalled | Symlink becomes dangling; hook fails loudly at execution ("command not found") |
| First install (no prior entry) | Symlink created, stable path registered — same as update path |
| Pre-existing user symlink at stable path | Overwritten unconditionally |
| Concurrent sessions at startup | Both write the same stable path; `_atomic_write_json` ensures no corruption |

## Migration Bridge

Existing installations may carry the old versioned path in `settings.json`.

**Bridge release:** Retain the full eviction loop (`_is_stale_bento_entry` +
`kept` loop) in the first release that ships this change. Mark it:

```python
# TODO(bento-stable-symlink): remove after migration release ships
```

The eviction loop will migrate existing versioned entries to the stable path
on first session after upgrade.

**Follow-up release:** File a separate Beads issue to delete the eviction
block. The eviction code is:
- `_is_stale_bento_entry()` — lines 104–131
- `kept` loop in `register()` — lines 143–151
- Both in `catalog/hooks/bento/claude/scripts/register-require-worktree-hook.py`

## Implementation Scope

**In scope:**
- `catalog/hooks/bento/claude/scripts/register-require-worktree-hook.py`
- `tests/test_register_require_worktree_hook.py` (new test cases)
- Filing a follow-up Beads issue for eviction-loop removal

**Out of scope:**
- `require-worktree.sh` itself (no changes)
- Plugin build or versioning pipeline
- Other hooks with the same versioned-path pattern (future work)

## Test Coverage

Extend `tests/test_register_require_worktree_hook.py` with:

1. Symlink created on first run at the stable path.
2. Symlink updated atomically when target changes (simulated version bump via
   a new plugin root directory).
3. Pre-existing symlink at stable path is overwritten (even if it pointed
   elsewhere).
4. `settings.json` is written with the stable path, not the versioned path.
5. Eviction loop removes an old versioned entry and replaces it with the
   stable path (bridge-release behaviour).

## Acceptance Checks

- After a plugin upgrade, `settings.json` contains the stable symlink path.
- `$HOME/.claude/hooks/bento/require-worktree.sh` resolves to the current
  versioned script after each session start.
- No duplicate hook entries accumulate across multiple session starts.
- Existing versioned-path entries are migrated on first session after upgrade.
- Pre-existing symlink is overwritten unconditionally.
- When the plugin cache is purged, the symlink is dangling and the hook fails
  loudly — no silent stale-copy execution.
- Eviction loop present in bridge release, absent in the next.
