# Tracker Migration Checklist

Use this checklist when moving a repo from one issue tracker to another (e.g.
Beads → GitHub Issues, or the reverse). It is tracker-agnostic; "old tracker"
and "new tracker" stand in for whichever pair applies. Follow it in order — the
common failures are dropped issues and abandoned tracker residue, and both are
prevented by steps below.

## 1. Migrate open issues with a reconciliation count

- Export every **open** issue from the old tracker. Do not migrate closed
  issues; they are historical and stay with the archived state (step 2).
- Re-file each open issue in the new tracker. On each new issue, record a
  `migrated-from: <old-tracker> <old-id>` line so provenance survives.
- Deliberately decide what happens to each exported issue: either it is filed
  in the new tracker, or it is dropped with a stated reason (obsolete,
  duplicate, already done). Do not silently drop.
- Reconcile the counts before declaring the migration done:

  ```
  N open exported = N filed + N dropped-with-reason
  ```

  Record this reconciliation somewhere durable (the migration commit message,
  a tracking issue, or the archival note from step 2). An unreconciled count is
  the signature of lost work.

## 2. Archive the old tracker's state deliberately

- Decide explicitly between removing the old tracker's state and keeping it as
  a labeled archive. Do not leave it in an in-between state.
- **Never** leave a hand-renamed directory (e.g. `.not-using-beads-anymore/`)
  sitting untracked in the working tree. Untracked residue is invisible to
  reviewers, survives for weeks, and hides whether open issues were re-filed.
- If removing: delete the old tracker's files and databases in a commit whose
  message states the migration and points at the reconciliation from step 1.
- If keeping: commit the archived state under a clearly labeled path (e.g.
  `archive/<old-tracker>/`) with a short `README` or commit message explaining
  it is a decommissioned tracker snapshot, when it was frozen, and where active
  issues now live.

## 3. Clean up tracker-specific `.gitignore` entries

- Once the old tracker is fully decommissioned, remove its `.gitignore` block
  (e.g. a stale "Beads / Dolt files" section). A leftover ignore block for a
  dead tracker is misleading residue and can silently hide files.
- Add any `.gitignore` entries the **new** tracker needs in the same pass.

## 4. Link this checklist from both issue-flow skills

- Both `beads-issue-flow` and `github-issue-flow` SKILL.md files link this
  checklist under a "Migrating to/from this tracker" heading so the migration
  path is discoverable from whichever tracker a repo currently uses.

## Post-migration verification

- The new tracker lists every issue that was supposed to migrate, and the
  reconciliation count balances.
- `git status` is clean: no untracked old-tracker directory remains.
- `.gitignore` contains no block for the decommissioned tracker.
- The repo's canonical tracker documentation names the new tracker, not the
  old one.
