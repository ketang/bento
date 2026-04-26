# Bugshot Standalone Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bugshot a standalone marketplace plugin by moving it from `EXTERNAL_SKILLS["bento"]` (bundled inside bento) to `EXTERNAL_PLUGINS` (a top-level marketplace pointer to `ketang/bugshot`).

**Architecture:** Two data changes in `scripts/build-plugins`: clear bugshot out of `EXTERNAL_SKILLS` and add it to `EXTERNAL_PLUGINS`. The `write_claude_marketplace` function already renders `EXTERNAL_PLUGINS` entries into the marketplace JSON with a GitHub source reference — no logic changes needed. `PLUGIN_ORDER` is not touched because it is validated against `plugin-versions.json` and external-only plugins have no bento-managed version.

**Tech Stack:** Python 3, unittest, `scripts/build-plugins` (single-file build script), `tests/test_build_plugins.py`

---

### Task 1: Replace the old bugshot-in-bento test with three new tests

**Files:**
- Modify: `tests/test_build_plugins.py`

The test `test_external_skills_registry_declares_bugshot_under_bento` currently asserts that bugshot is registered in `EXTERNAL_SKILLS["bento"]`. That assertion must be inverted. Replace it with three focused tests that together cover the new desired state.

- [ ] **Step 1: Delete the old test**

In `tests/test_build_plugins.py`, remove the entire method `test_external_skills_registry_declares_bugshot_under_bento` (lines ~191–197):

```python
    def test_external_skills_registry_declares_bugshot_under_bento(self) -> None:
        module = load_build_plugins_module()
        entries = module.EXTERNAL_SKILLS.get("bento", [])
        bugshot = next((e for e in entries if e["name"] == "bugshot"), None)
        self.assertIsNotNone(bugshot, "bugshot should be registered as an external skill of bento")
        self.assertEqual(bugshot["repo"], "ketang/bugshot")
        self.assertRegex(bugshot["ref"], r"^[0-9a-f]{40}$", "ref should be a pinned commit SHA")
```

- [ ] **Step 2: Add `test_bugshot_not_in_bento_external_skills`**

Add after the last test method in `BuildPluginsTest`:

```python
    def test_bugshot_not_in_bento_external_skills(self) -> None:
        module = load_build_plugins_module()
        bento_skills = module.EXTERNAL_SKILLS.get("bento", [])
        bugshot = next((e for e in bento_skills if e["name"] == "bugshot"), None)
        self.assertIsNone(bugshot, "bugshot must not be bundled as an external skill of bento")
```

- [ ] **Step 3: Add `test_bugshot_in_external_plugins`**

```python
    def test_bugshot_in_external_plugins(self) -> None:
        module = load_build_plugins_module()
        bugshot = next((e for e in module.EXTERNAL_PLUGINS if e["name"] == "bugshot"), None)
        self.assertIsNotNone(bugshot, "bugshot should be registered in EXTERNAL_PLUGINS")
        self.assertEqual(bugshot["repo"], "ketang/bugshot")
```

- [ ] **Step 4: Add `test_bugshot_appears_in_claude_marketplace_as_external`**

This test uses `self.module` (which has `EXTERNAL_SKILLS = {}` set in setUp, preventing any GitHub cloning). `EXTERNAL_PLUGINS` is not overridden in setUp, so it reads the real value from the script.

```python
    def test_bugshot_appears_in_claude_marketplace_as_external(self) -> None:
        self.module.build_repo(run_verification=False)
        marketplace = json.loads(
            (self.root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        bugshot = next((p for p in marketplace["plugins"] if p["name"] == "bugshot"), None)
        self.assertIsNotNone(bugshot, "bugshot should appear in the claude marketplace")
        self.assertNotIn("version", bugshot, "external plugin entry must not carry a version field")
        self.assertIn("source", bugshot)
        self.assertEqual(bugshot["source"]["source"], "github")
        self.assertEqual(bugshot["source"]["repo"], "ketang/bugshot")
```

- [ ] **Step 5: Add `test_bugshot_not_bundled_in_bento_plugin`**

```python
    def test_bugshot_not_bundled_in_bento_plugin(self) -> None:
        self.module.build_repo(run_verification=False)
        for platform in ("claude", "codex"):
            bento_bugshot = self.root / "plugins" / platform / "bento" / "skills" / "bugshot"
            self.assertFalse(
                bento_bugshot.exists(),
                f"bugshot must not be bundled inside bento for {platform}",
            )
```

- [ ] **Step 6: Run only the new/changed tests to confirm they fail for the right reason**

```bash
python3 -m unittest tests.test_build_plugins.BuildPluginsTest.test_bugshot_not_in_bento_external_skills tests.test_build_plugins.BuildPluginsTest.test_bugshot_in_external_plugins tests.test_build_plugins.BuildPluginsTest.test_bugshot_appears_in_claude_marketplace_as_external tests.test_build_plugins.BuildPluginsTest.test_bugshot_not_bundled_in_bento_plugin -v
```

Expected: all four FAIL.
- `test_bugshot_not_in_bento_external_skills` — fails because bugshot IS still in `EXTERNAL_SKILLS["bento"]`
- `test_bugshot_in_external_plugins` — fails because `EXTERNAL_PLUGINS` is still empty
- `test_bugshot_appears_in_claude_marketplace_as_external` — fails because bugshot is absent from marketplace
- `test_bugshot_not_bundled_in_bento_plugin` — this may already pass because setUp overrides EXTERNAL_SKILLS to `{}`, preventing bundling during test builds; that is fine

---

### Task 2: Update `scripts/build-plugins` to move bugshot to `EXTERNAL_PLUGINS`

**Files:**
- Modify: `scripts/build-plugins`

Two data-only changes. No logic changes are required — `write_claude_marketplace` already renders `EXTERNAL_PLUGINS` entries into the marketplace.

- [ ] **Step 1: Clear `EXTERNAL_SKILLS`**

Find (around line 38):

```python
EXTERNAL_SKILLS: dict[str, list[dict]] = {
    "bento": [
        {
            "name": "bugshot",
            "repo": "ketang/bugshot",
            "ref": "856774fe1f5093c109d8318e6363d2e6a402e146",
            "include": [
                "SKILL.md",
                "ansi_render.py",
                "bugshot_cli.py",
                "bugshot_workflow.py",
                "gallery_server.py",
                "static",
                "templates",
            ],
        },
    ],
}
```

Replace with:

```python
EXTERNAL_SKILLS: dict[str, list[dict]] = {}
```

- [ ] **Step 2: Populate `EXTERNAL_PLUGINS`**

Find (around line 36):

```python
EXTERNAL_PLUGINS: list[dict] = []
```

Replace with:

```python
EXTERNAL_PLUGINS: list[dict] = [
    {
        "name": "bugshot",
        "description": "Ephemeral screenshot gallery for visual bug review and issue filing",
        "repo": "ketang/bugshot",
    },
]
```

- [ ] **Step 3: Run all four new tests**

```bash
python3 -m unittest tests.test_build_plugins.BuildPluginsTest.test_bugshot_not_in_bento_external_skills tests.test_build_plugins.BuildPluginsTest.test_bugshot_in_external_plugins tests.test_build_plugins.BuildPluginsTest.test_bugshot_appears_in_claude_marketplace_as_external tests.test_build_plugins.BuildPluginsTest.test_bugshot_not_bundled_in_bento_plugin -v
```

Expected: all four PASS.

- [ ] **Step 4: Run the full test suite**

```bash
BENTO_SKIP_CLAUDE_VALIDATE=1 python3 -m unittest discover -s tests -t . -v
```

Expected: all tests pass. If `test_fetch_external_skill_*` tests or `test_bugshot_external_skill_not_built_as_top_level_plugin` fail, investigate before proceeding.

- [ ] **Step 5: Commit**

```bash
git add scripts/build-plugins tests/test_build_plugins.py
git commit -m "feat(bugshot): promote bugshot to standalone marketplace plugin"
```
