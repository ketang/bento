# Removable-Code Patterns

Narrative guide to what tends to be removable and how to find each kind. Not a rigid taxonomy. Use judgment.

Every finding must carry all four evidence pieces (see `SKILL.md`). If you cannot collect them, drop the finding rather than file a weak one.

## Unreferenced symbols (functions, classes, exports, files)

**Look for:** definitions where every search comes back empty.

**Searches to run before flagging:**
- `Grep` the symbol name across the whole scope (source, tests, configs, templates, docs, examples).
- Look for exports from any index/barrel file.
- Scan for dynamic lookups: string-based imports, `getattr`/`eval`/`hasattr`/reflection equivalents, `require()` with computed names, glob-loaded plugins.
- Check public API surface: package manifests, `__all__`, `exports` fields, OpenAPI/GraphQL schemas, generated bindings.

**Evidence required:** every search above plus its result.

**Blast radius cues:** module-private (safe) → package-internal → public API → external consumers in workspace siblings.

## Near-duplicates

**Look for:** functions with the same shape solving the same problem in two places.

**Searches to run:**
- Group functions by signature (parameter count + types + return type) within and across chunks.
- For same-signature groups, compare bodies. Tokens that match >70% by line count are candidates.
- Confirm semantic equivalence by reading both, not just by line similarity.

**Evidence required:** location of both, similarity ratio, semantic confirmation note, which one should survive (and why).

**Blast radius cues:** if one is in a library module and the other is a copy in a consumer, consolidate at the library. If both are in consumers, consider whether either belongs in shared code.

## Wrappers and indirections with ≤ 1 caller

**Look for:** functions, classes, interfaces, or modules whose only job is to forward to something else.

**Patterns:**
- Single-line wrapper functions.
- Interfaces with one implementation that no one mocks.
- Base classes with one subclass.
- Config options nothing sets.
- Plugin points with no third-party use.

**Searches to run:** caller count via `Grep`, plus a check that the wrapper adds no behavior (no validation, no logging, no error translation).

**Evidence required:** caller count, the wrapper body, what (if anything) it actually adds.

**Blast radius cues:** Module-private wrappers (safe) → package-internal → public interface or exported symbol (high risk; external callers may depend on the indirection). Check whether the wrapper is in an index/barrel export.

## Fully rolled-out feature flags

**Look for:** flag checks whose value has been pinned for a long time.

**Searches to run:**
- Locate flag definitions (look for the project's flag system: env vars, `LaunchDarkly`, `growthbook`, custom registries, `process.env.FEATURE_*`).
- For each flag, find every read site.
- Check the flag's defined default and any config files / dashboards in the repo.
- `git log -p` the flag-set sites to estimate how long the value has been stable.

**Evidence required:** flag name, definition site, all read sites, default value, last-changed date from git, recommended branch to keep.

**Blast radius cues:** Single-service env var (contained) → shared config or LaunchDarkly/remote flag (check all services that read it). Verify the flag is not read from deployment configs, Helm charts, or infrastructure-as-code files outside the repo.

## Finished migrations and version-compat shims

**Look for:** code labeled "legacy", "v1", "old", "compat", "transition", or dated comments.

**Searches to run:**
- `Grep` for `legacy|deprecated|TODO.*remove|v1|compat` across the scope.
- For each match, check whether the documented sunset condition has passed (often in a comment near the call site).
- Look for parallel implementations: `*_v2.py`, `*-new.ts`, `New<ClassName>`, etc., and check whether the old one is still called.

**Evidence required:** the marker, the condition for removal, evidence that the condition is met, callers of the deprecated path.

**Blast radius cues:** Single-file shim (contained) → package-level compat layer → cross-service protocol shim (verify no consumers in sibling packages or workspace siblings before proposing removal).

## Commented-out blocks

**Look for:** large blocks of code disabled by line or block comments.

**Searches to run:**
- For line-comment blocks (JS/TS/Go/Rust/Java): `grep -n "^[[:space:]]*//" <file>` — runs of 3+ consecutive commented lines are candidates.
- For block comments: scan for `/*` ... `*/` or `"""` ... `"""` blocks spanning more than 5 lines.
- For Python line-comment blocks: `grep -n "^[[:space:]]*#" <file>` — same 3-consecutive-line heuristic.
- Run `git blame` on each candidate block to get the last-changed date; skip blocks changed within 90 days.
- Check for any surrounding prose comment referencing the disabled block (e.g., "see disabled block above" — a signal it's a known-intentional disable).

Be conservative. Comment-outs sometimes preserve known-good fallbacks. Only flag blocks where:
- The block is older than 90 days in `git blame`, AND
- The block is not referenced from any nearby comment (e.g. "see disabled block above"), AND
- A working alternative is in the same file.

**Evidence required:** block location, age from blame, nearby context, the alternative.

## Dead dependencies

**Look for:** entries in `package.json` / `requirements.txt` / `go.mod` / `Cargo.toml` that no code imports.

**Searches to run:**
- For each declared dependency, `Grep` for its import name across the source tree.
- Distinguish runtime deps (`dependencies`) from dev deps; report both but mark separately.
- Check for transitive use via tool configs, lint configs, build scripts.

**Evidence required:** dependency name, no-imports search result.

**Blast radius cues:** Dev dependency (safe to remove; affects only the build toolchain) → runtime dependency (check for transitive consumers and dynamic requires before filing). Peer dependencies are especially risky — flag but don't propose removal without noting the peer constraint.

**Do not propose uninstalling.** Report only; the issue implementer runs the uninstall.
