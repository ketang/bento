# Stable Symlink Hook Registration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the versioned absolute path in `settings.json` with a stable symlink so the hook registration path never changes between plugin versions.

**Architecture:** `register-require-worktree-hook.py` gains two new functions — `_stable_symlink_path()` returning `$HOME/.claude/hooks/bento/require-worktree.sh`, and `_update_symlink(target, stable)` which atomically creates/updates that symlink on each SessionStart. `main()` calls these before `register()`, passing the stable path as the command string instead of the versioned path. The eviction loop is retained with a TODO comment for one migration release.

**Tech Stack:** Python 3 stdlib only (`os`, `pathlib`, `tempfile`). Tests use `unittest` with a fake-home fixture already in place.

---

### Task 1: Write failing tests for the new symlink behavior

**Files:**
- Modify: `tests/test_register_require_worktree_hook.py`

- [ ] **Step 1: Understand the stable path the tests will check**

  The stable symlink in tests lives at:
  ```
  self.fake_home / ".claude" / "hooks" / "bento" / "require-worktree.sh"
  ```
  The versioned target it points at is:
  ```
  self.plugin_root / "hooks" / "scripts" / "require-worktree.sh"
  ```

- [ ] **Step 2: Add a helper to the test class**

  Add `_stable_symlink_path()` and `_stable_symlink_dir()` helpers to `RegisterRequireWorktreeHookTest`, immediately after `_read_settings`:

  ```python
  def _stable_symlink_dir(self) -> Path:
      return self.fake_home / ".claude" / "hooks" / "bento"

  def _stable_symlink_path(self) -> Path:
      return self._stable_symlink_dir() / "require-worktree.sh"
  ```

- [ ] **Step 3: Add test — symlink created on first run**

  Add after existing tests:

  ```python
  def test_symlink_created_on_first_run(self) -> None:
      self.assertEqual(self._run(), 0)
      stable = self._stable_symlink_path()
      self.assertTrue(stable.is_symlink(), f"Expected symlink at {stable}")
      self.assertEqual(
          Path(os.readlink(stable)),
          self.plugin_root / "hooks" / "scripts" / "require-worktree.sh",
      )
  ```

- [ ] **Step 4: Add test — symlink updated when plugin version changes**

  ```python
  def test_symlink_updated_on_version_bump(self) -> None:
      # First run: plugin_root v1
      self.assertEqual(self._run(), 0)

      # Simulate a version bump: new plugin root directory
      new_plugin_root = self.root / "plugin-v2"
      (new_plugin_root / "hooks" / "scripts").mkdir(parents=True)
      new_script = new_plugin_root / "hooks" / "scripts" / "require-worktree.sh"
      new_script.write_text("#!/bin/sh\n# v2\n", encoding="utf-8")

      old_home = os.environ.get("HOME")
      os.environ["HOME"] = str(self.fake_home)
      try:
          self.module.main(
              ["register-require-worktree-hook.py", str(new_plugin_root)]
          )
      finally:
          if old_home is None:
              os.environ.pop("HOME", None)
          else:
              os.environ["HOME"] = old_home

      stable = self._stable_symlink_path()
      self.assertTrue(stable.is_symlink())
      self.assertEqual(
          Path(os.readlink(stable)),
          new_plugin_root / "hooks" / "scripts" / "require-worktree.sh",
      )
  ```

- [ ] **Step 5: Add test — pre-existing symlink at stable path is overwritten**

  ```python
  def test_preexisting_symlink_at_stable_path_is_overwritten(self) -> None:
      # Create a symlink pointing somewhere unrelated
      stable = self._stable_symlink_path()
      stable.parent.mkdir(parents=True, exist_ok=True)
      unrelated = self.root / "unrelated-script.sh"
      unrelated.write_text("#!/bin/sh\n", encoding="utf-8")
      os.symlink(unrelated, stable)

      self.assertEqual(self._run(), 0)

      self.assertTrue(stable.is_symlink())
      self.assertEqual(
          Path(os.readlink(stable)),
          self.plugin_root / "hooks" / "scripts" / "require-worktree.sh",
      )
  ```

- [ ] **Step 6: Add test — settings.json records stable path, not versioned path**

  ```python
  def test_settings_json_has_stable_path_not_versioned_path(self) -> None:
      self.assertEqual(self._run(), 0)

      stable = str(self._stable_symlink_path())
      versioned = str(
          self.plugin_root / "hooks" / "scripts" / "require-worktree.sh"
      )
      settings = self._read_settings()
      commands = [
          hook["command"]
          for entry in settings["hooks"]["PreToolUse"]
          for hook in entry["hooks"]
      ]
      self.assertIn(stable, commands)
      self.assertNotIn(versioned, commands)
  ```

- [ ] **Step 7: Run the new tests to confirm they all fail**

  ```bash
  cd /home/ketan/.local/share/worktrees/bento-zew
  python -m pytest tests/test_register_require_worktree_hook.py \
    -k "symlink or stable_path" -v 2>&1 | tail -30
  ```

  Expected: all four new tests FAIL (function not yet implemented).

- [ ] **Step 8: Commit the failing tests**

  ```bash
  git add tests/test_register_require_worktree_hook.py
  git commit -m "test: add failing tests for stable symlink hook registration (bento-zew)"
  ```

---

### Task 2: Implement stable symlink logic

**Files:**
- Modify: `catalog/hooks/bento/claude/scripts/register-require-worktree-hook.py`

- [ ] **Step 1: Add `_stable_symlink_path()` function**

  Insert after `_settings_path()` (currently line 55):

  ```python
  def _stable_symlink_path() -> Path:
      """Stable (version-independent) path for the require-worktree.sh symlink.

      Lives under ~/.claude/hooks/bento/ — a location owned by this script.
      Any pre-existing file or symlink there is overwritten unconditionally.
      """
      return Path(os.environ.get("HOME", str(Path.home()))) / ".claude" / "hooks" / "bento" / "require-worktree.sh"
  ```

- [ ] **Step 2: Add `_update_symlink()` function**

  Insert after `_stable_symlink_path()`:

  ```python
  def _update_symlink(target: Path, stable: Path) -> None:
      """Atomically create or update stable to point at target.

      Uses mkstemp to get a unique temp name in the same directory, removes the
      placeholder file, creates a symlink at that path, then os.replace()s it
      onto stable — atomic on POSIX so concurrent sessions never see a missing
      or broken link mid-update.
      """
      stable.parent.mkdir(parents=True, exist_ok=True)
      fd, tmp_name = tempfile.mkstemp(prefix=".symlink-", dir=str(stable.parent))
      os.close(fd)
      tmp_path = Path(tmp_name)
      try:
          tmp_path.unlink()
          os.symlink(target, tmp_path)
          os.replace(tmp_path, stable)
      except Exception:
          try:
              tmp_path.unlink(missing_ok=True)
          except OSError:
              pass
          raise
  ```

- [ ] **Step 3: Add TODO comment to the eviction loop in `register()`**

  Find the comment `# Evict stale bento require-worktree.sh entries from older plugin versions.`
  (currently line 142) and prepend:

  ```python
  # TODO(bento-stable-symlink): remove this entire block after migration release ships.
  # It exists only to sweep versioned paths written by older plugin versions.
  # Evict stale bento require-worktree.sh entries from older plugin versions.
  ```

- [ ] **Step 4: Update `main()` to use symlink and stable path**

  Replace the `try` block in `main()` (lines 193–202):

  **Before:**
  ```python
      try:
          plugin_root = Path(argv[1])
          command = str(plugin_root / "hooks" / "scripts" / "require-worktree.sh")
          settings_path = _settings_path()
          settings = _load_settings(settings_path)
          if settings is None:
              return 0
          if register(settings, command):
              _atomic_write_json(settings_path, settings)
      except Exception:
          return 0
  ```

  **After:**
  ```python
      try:
          plugin_root = Path(argv[1])
          target = plugin_root / "hooks" / "scripts" / "require-worktree.sh"
          stable = _stable_symlink_path()
          _update_symlink(target, stable)
          command = str(stable)
          settings_path = _settings_path()
          settings = _load_settings(settings_path)
          if settings is None:
              return 0
          if register(settings, command):
              _atomic_write_json(settings_path, settings)
      except Exception:
          return 0
  ```

- [ ] **Step 5: Run only the new tests to confirm they pass**

  ```bash
  python -m pytest tests/test_register_require_worktree_hook.py \
    -k "symlink or stable_path" -v 2>&1 | tail -20
  ```

  Expected: all four new tests PASS.

- [ ] **Step 6: Run the full test suite to check for regressions**

  ```bash
  python -m pytest tests/test_register_require_worktree_hook.py -v 2>&1 | tail -40
  ```

  Expected output: some existing tests will now FAIL because they assert the
  versioned path (`self.plugin_root/...`) but `settings.json` now contains the
  stable path. Note which tests fail — they are fixed in Task 3.

- [ ] **Step 7: Commit the implementation**

  ```bash
  git add catalog/hooks/bento/claude/scripts/register-require-worktree-hook.py
  git commit -m "feat: use stable symlink path for require-worktree hook registration (bento-zew)"
  ```

---

### Task 3: Update existing tests to expect the stable path

**Files:**
- Modify: `tests/test_register_require_worktree_hook.py`

The following existing tests assert the versioned path. Each needs updating to
assert the stable path instead.

- [ ] **Step 1: Fix `test_registers_all_edit_tools`**

  **Before** (line 82–84):
  ```python
              command = by_matcher[matcher]["hooks"][0]["command"]
              self.assertEqual(
                  command,
                  f"{self.plugin_root}/hooks/scripts/require-worktree.sh",
              )
  ```

  **After:**
  ```python
              command = by_matcher[matcher]["hooks"][0]["command"]
              self.assertEqual(
                  command,
                  str(self._stable_symlink_path()),
              )
  ```

- [ ] **Step 2: Fix `test_preserves_existing_settings_and_hooks`**

  **Before** (line 116):
  ```python
          self.assertIn(f"{self.plugin_root}/hooks/scripts/require-worktree.sh", commands)
  ```

  **After:**
  ```python
          self.assertIn(str(self._stable_symlink_path()), commands)
  ```

- [ ] **Step 3: Fix `test_evicts_stale_versioned_entries`**

  **Before** (line 162):
  ```python
          current = f"{self.plugin_root}/hooks/scripts/require-worktree.sh"
  ```

  **After:**
  ```python
          current = str(self._stable_symlink_path())
  ```

- [ ] **Step 4: Fix `test_claude_invocation_writes_settings`**

  **Before** (line 222–224):
  ```python
          self.assertIn(
              f"{self.plugin_root}/hooks/scripts/require-worktree.sh", commands
          )
  ```

  **After:**
  ```python
          self.assertIn(str(self._stable_symlink_path()), commands)
  ```

- [ ] **Step 5: Run the full test suite and confirm all tests pass**

  ```bash
  python -m pytest tests/test_register_require_worktree_hook.py -v 2>&1 | tail -30
  ```

  Expected: all tests PASS, zero failures.

- [ ] **Step 6: Commit the test updates**

  ```bash
  git add tests/test_register_require_worktree_hook.py
  git commit -m "test: update existing tests to assert stable symlink path (bento-zew)"
  ```

---

### Task 4: Rebuild plugins and verify generated output

**Files:**
- Modify (generated): `plugins/claude/bento/hooks/scripts/register-require-worktree-hook.py`

- [ ] **Step 1: Run the build script**

  ```bash
  scripts/build-plugins 2>&1 | tail -20
  ```

  Expected: exits 0, no errors.

- [ ] **Step 2: Confirm the generated script matches the source**

  ```bash
  diff catalog/hooks/bento/claude/scripts/register-require-worktree-hook.py \
       plugins/claude/bento/hooks/scripts/register-require-worktree-hook.py
  ```

  Expected: no diff (build copies the file verbatim).

- [ ] **Step 3: Commit the regenerated plugin artifacts**

  ```bash
  git add plugins/
  git commit -m "chore: regenerate plugin artifacts after stable symlink change (bento-zew)"
  ```

---

### Task 5: File follow-up Beads issue for eviction-loop removal

- [ ] **Step 1: Create the follow-up issue**

  Run from the primary checkout (`/path/to/bento`, not the worktree):

  ```bash
  bd create \
    --title "Remove eviction loop from register-require-worktree-hook.py after stable-symlink migration" \
    --description "The eviction loop added in bento-zew (\`_is_stale_bento_entry\`, the \`kept\` loop in \`register()\`, marked TODO(bento-stable-symlink)) is a one-release migration bridge. Once the stable-symlink release has shipped and existing installations have had a session start, the loop can be removed.

  Files to edit:
  - \`catalog/hooks/bento/claude/scripts/register-require-worktree-hook.py\`
    - Delete \`_is_stale_bento_entry()\` (was lines 104–131 before bento-zew)
    - Delete the TODO comment and \`kept\` loop in \`register()\` (was lines 142–151 before bento-zew)
  - \`tests/test_register_require_worktree_hook.py\`
    - Delete \`test_evicts_stale_versioned_entries\` and \`test_does_not_evict_other_plugins\`

  Run \`scripts/build-plugins\` after editing. Run \`python -m pytest tests/test_register_require_worktree_hook.py -v\` to confirm no regressions.

  Acceptance: the two eviction functions and their tests are gone; all remaining tests pass; plugin artifacts are regenerated."
  ```

  Note the issue ID printed.

- [ ] **Step 2: Confirm the issue was created**

  ```bash
  bd show <issue-id>
  ```

  Expected: issue visible with correct title and description.

---
