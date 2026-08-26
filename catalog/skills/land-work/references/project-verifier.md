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
2. `<home-config-root>/agent-plugins/bento/bento/land-work/verifier.json` — see
   [docs/specs/2026-04-24-agent-plugins-convention-design.md](../../../../docs/specs/2026-04-24-agent-plugins-convention-design.md)
   for the platform-specific home config root (`$XDG_CONFIG_HOME` if set,
   else `~/.config` on Linux, `~/Library/Application Support` on macOS, or
   `%APPDATA%` on Windows)

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
  failure, or timeout is a landing failure.
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
taxonomy, guessed hook, or interactive choice.

## Diagnostics

The helper emits one JSON object on stdout with `base_sha`, `head_sha`,
`candidate`, categorized `changed_paths`, `relevant_paths`, the exact
`exemptions` used, the `verifier_command`, `verifier_status`,
`selected_check_count`, and `unverified_paths`. Diagnostics never include file
contents. Exit 0 means verified; any nonzero exit stops the landing.
