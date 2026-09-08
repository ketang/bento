# Project Verifier Manifest Contract

`land-work-run-verifier.py` gates a landing on a repo-configured verifier so
that a real diff can never land against a zero-check result. It is separate from
generic `pre` hooks: a hook's exit 0 is never project verification.

To create the manifest and its wrapper in a repo that has none, use the
`bento:wire-land-verifier` skill rather than hand-authoring both under time
pressure mid-landing.

## Manifest location and precedence

The manifest is `verifier.json` under the land-work extension root, discovered
across the same candidate-root chain as other project extensions:

1. `<repo-root>/.agent-plugins/bento/bento/land-work/verifier.json` (repo-local)
2. `<home-config-root>/agent-plugins/bento/bento/land-work/verifier.json` —
   `$XDG_CONFIG_HOME` if set, else the platform default (`~/.config` on
   Linux, `~/Library/Application Support` on macOS, `%APPDATA%` on
   Windows); see
   [`home_config_root()`](../../launch-work/scripts/agent_plugins_resolver.py)
   for the exact resolution

The **first existing manifest wins as a whole** — repo-local overrides
user-global. Commands and exemptions are never merged across roots, and a
verifier is never inferred from generic hook names.

## Schema (version 1)

```json
{
  "schema_version": 1,
  "command": ["./scripts/project-verifier-json.sh"],
  "verified_noop": [
    {
      "path": "docs/generated/manifest.json",
      "reason": "Generated manifest identity is verified by its producer"
    }
  ]
}
```

- `command` — a nonempty argv array executed without a shell in the candidate
  worktree. The verifier's final stdout line must be one JSON object:
  `{"schema_version":1,"status":"passed","selected_checks":[{"name":"make test-quick","status":"passed"}]}`.
  Missing/invalid JSON, an unknown status, a failed selected check, command
  failure, or timeout is a landing failure — reported in the diagnostics JSON's
  `verifier_status` as one of `passed`, `failed`, `killed`, or `timeout` (see
  "Verifier status and the raw log" below), with the command's raw
  stdout+stderr persisted to `<candidate>/.land-work/verifier.log` (or
  `--log <path>`) for post-mortem.
- `verified_noop` — defaults to empty. Each entry needs one normalized,
  repo-relative exact file path and a nonempty reason. Absolute paths, `..`,
  globs, directory/prefix entries, duplicates, and paths that exist in neither
  the candidate nor its deletion side are rejected. An exact declaration exempts
  only that exact path — `docs/a.md` never exempts `docs/a.md.bak` or a child.

## Candidate diff union and precedence

The helper builds a deduplicated repo-relative path union in the supplied
candidate worktree from committed base..head changes (including additions,
modifications, deletions, and both sides of renames), staged changes, unstaged
tracked changes, and nonignored untracked files. Ignored files never enter the
union. All Git commands target the candidate worktree explicitly; a linked
worktree never falls back to the primary checkout's index or working tree.

1. Normalize the union and subtract only exact, valid `verified_noop` entries.
2. If no relevant paths remain, a `passed` verifier with `selected_checks: []`
   passes; diagnostics list the exact exemptions used.
3. If any relevant path remains, `selected_checks` must contain at least one
   passed check. A passed verifier with zero selected checks exits nonzero and
   the landing stops before lease verification or merge.

A missing verifier manifest with a nonempty relevant diff is also nonzero and
reports the config path to create. There is no generic fallback gate, path
taxonomy, guessed hook, or interactive choice. `land-work`'s workflow invokes
`wire-land-verifier` inline on this specific error rather than stopping and
deferring the fix to a separately remembered step; see the missing-manifest
exception in `land-work/SKILL.md` step 8. `wire-land-verifier`'s own
confirm-before-draft and explicit-go-ahead-before-apply gates are unchanged —
this script still never infers or rubber-stamps a verifier command.

## Verifier status and the raw log

`verifier_status` is always one of four values:

- `passed` — the command produced a valid, schema-matching result whose
  status was `passed` and every relevant path was covered by a passed
  selected check (or nothing relevant remained).
- `failed` — the command produced a valid, schema-matching result, but that
  result reports a real failure: an explicit `status` other than `passed`, a
  selected check that didn't pass, a malformed `selected_checks` shape, or a
  `passed` result with zero selected checks against a nonempty relevant diff.
  This is a genuine gate failure — fix the underlying problem; retrying an
  unchanged candidate will not help.
- `killed` — no usable result was ever produced: the child died by signal (an
  external SIGKILL, not this helper's own `--timeout`), it exited without
  emitting any final JSON line, or what it emitted did not parse as a
  schema-matching JSON object. This status exists because none of those cases
  can be told apart from an externally killed process, so — unlike
  `failed` — it is reasonable to inspect the log and rerun once before
  concluding the gate itself is broken.
- `timeout` — this helper's own `--timeout` killed the command. The command
  is likely too slow for the given budget, not necessarily broken.

The command's raw, unfiltered stdout+stderr is always persisted to
`<candidate>/.land-work/verifier.log` (override with `--log <path>`),
regardless of `verifier_status`. On `killed` or `timeout`, the diagnostics
JSON also includes `verifier_log_tail` (the log's last 20 lines) inline, so a
first look at what happened does not require a separate file read; `killed`
additionally includes `killed_signal` when the child died by signal.

## Diagnostics

The helper emits one JSON object on stdout with `base_sha`, `head_sha`,
`candidate`, categorized `changed_paths`, `relevant_paths`, the exact
`exemptions` used, the `verifier_command`, `verifier_status`, `verifier_log`,
`selected_check_count`, and `unverified_paths`. Diagnostics never include file
contents beyond the verifier's own stdout/stderr captured in the log and its
tail. Exit 0 means verified; any nonzero exit stops the landing.
