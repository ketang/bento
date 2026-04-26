# Bugshot Standalone Plugin Design

**Date:** 2026-04-26

## Goal

Make `bugshot` available as a standalone installable plugin in the bento marketplace, completely separate from the `bento` plugin. Remove it from the `bento` bundle.

## Approach

External marketplace pointer. The `ketang/bugshot` repo already has a `.claude-plugin/plugin.json` (v1.0.5), so bento only needs to register it as a marketplace entry. No local build or asset generation is needed for bugshot.

## Data Changes (`scripts/build-plugins`)

### 1. Remove bugshot from `EXTERNAL_SKILLS`

`EXTERNAL_SKILLS["bento"]` currently fetches bugshot from `ketang/bugshot` and bundles it as a skill inside the `bento` plugin. Remove the `bento` key (or set it to an empty list). This stops the build from producing `plugins/claude/bento/skills/bugshot/`.

### 2. Add bugshot to `EXTERNAL_PLUGINS`

```python
EXTERNAL_PLUGINS: list[dict] = [
    {
        "name": "bugshot",
        "description": "Ephemeral screenshot gallery for visual bug review and issue filing",
        "repo": "ketang/bugshot",
    },
]
```

### 3. Add `"bugshot"` to `PLUGIN_ORDER`

Controls its position in the marketplace listing. Bugshot has no `PLUGIN_DEFS` entry and is never locally materialized.

## Build Logic Changes (`build_repo`, `write_claude_marketplace`)

### `build_repo`

Skip plugins not in `PLUGIN_DEFS` when iterating `PLUGIN_ORDER`:

```python
for plugin in PLUGIN_ORDER:
    if plugin not in PLUGIN_DEFS:
        continue
    for platform in PLATFORMS:
        build_plugin(plugin, platform)
```

### `write_claude_marketplace`

`local_entries` iterates `PLUGIN_ORDER` filtered by `plugin_has_content`, which calls into `PLUGIN_DEFS`. Guard it to only include plugins that are in `PLUGIN_DEFS`:

```python
local_entries = [
    ...
    for plugin in PLUGIN_ORDER
    if plugin in PLUGIN_DEFS and plugin_has_content(plugin, "claude")
]
```

The marketplace output for bugshot (appended after local entries via `external_entries`):

```json
{
  "name": "bugshot",
  "description": "Ephemeral screenshot gallery for visual bug review and issue filing",
  "source": { "source": "github", "repo": "ketang/bugshot" },
  "author": { "name": "Ketan Gangatirkar" }
}
```

## Test Changes (`tests/test_build_plugins.py`)

### Remove

- `test_external_skills_registry_declares_bugshot_under_bento` — guards the behavior being reversed.

### Add

- `test_bugshot_in_external_plugins` — asserts `EXTERNAL_PLUGINS` contains an entry with `name == "bugshot"` and `repo == "ketang/bugshot"`.
- `test_bugshot_appears_in_claude_marketplace_as_external` — calls `build_repo(run_verification=False)`, reads `marketplace.json`, asserts bugshot is present with a GitHub source (not a `./plugins/...` path).
- `test_bugshot_not_bundled_in_bento_plugin` — asserts `plugins/claude/bento/skills/bugshot/` does not exist after build.

### Unchanged

- `test_bugshot_external_skill_not_built_as_top_level_plugin` — remains valid; bugshot still must not appear as a top-level materialized directory.
- All `test_fetch_external_skill_*` tests — `fetch_external_skill` function is unchanged.
