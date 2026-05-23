# Tools by Language

Optional language-specific tools the agent may shell out to if installed. Use these in addition to manual searches — they catch things grep misses, but they also produce false positives, so combine with the four evidence pieces.

Detect a language by manifest file at the chunk root, not by glob. A `package.json` makes the chunk TypeScript/JavaScript; `go.mod` makes it Go; `pyproject.toml` or `requirements.txt` makes it Python; `Cargo.toml` makes it Rust.

For each tool entry: what it finds, how to invoke, how to parse, what false positives to expect.

## TypeScript / JavaScript

### `knip`

**Finds:** unused files, exports, dependencies, types.

**Invoke:** `npx --yes knip --reporter json` from the chunk root.

**Parse:** top-level keys are `files`, `exports`, `types`, `dependencies`, `devDependencies`, `unlisted`. Each value is a list of locations.

**False positives:**
- Dynamic `import()` with computed paths.
- Files loaded by test runners not declared in config.
- Re-exports in barrels.

### `ts-prune`

**Finds:** exported symbols with no importers.

**Invoke:** `npx --yes ts-prune` from the chunk root (must have a `tsconfig.json`).

**Parse:** one line per finding: `path/to/file.ts:LINE - SymbolName (used in module)`. The `(used in module)` suffix means used internally — usually not removable.

**False positives:**
- Symbols re-exported from a public barrel.
- Symbols consumed by other workspaces in a monorepo (run per-package).

## Go

### `staticcheck`

**Finds:** unused variables, unreachable code, redundant code (U-series checks).

**Invoke:** `staticcheck ./...` from the chunk root.

**Parse:** lines of form `file.go:LINE:COL: message (Uxxxx)`. The `U`-prefixed codes are the unused-code checks.

**False positives:**
- Reflection-driven access (`reflect`).
- Code generated from build tags not enabled in the run.

### `go mod tidy` dry-run

**Finds:** unused modules in `go.mod`.

**Invoke:** copy `go.sum`/`go.mod` to a scratch dir, run `go mod tidy -v` there, diff against original.

**Parse:** any module that disappears from `go.mod` after tidy is a candidate.

**False positives:**
- Modules used only in build-tagged code that is not in the default build.

## Python

### `vulture`

**Finds:** unused functions, classes, imports, variables.

**Invoke:** `vulture --min-confidence 80 <chunk_root>`.

**Parse:** lines of form `path/file.py:LINE: unused <kind> '<name>' (NN% confidence)`.

**False positives:**
- Functions called by `getattr` / `__getattr__` / decorator registries.
- Test fixtures.
- Entry points declared in `pyproject.toml` / `setup.cfg`.

Always start at `--min-confidence 80`; lower confidences are noisy.

### `deadcode`

**Finds:** unused functions (modern alternative to vulture for newer Pythons).

**Invoke:** `deadcode <chunk_root>`.

**Parse:** lines of form `path/file.py:LINE: unused function ...`.

**False positives:** same dynamic-lookup risks as vulture.

## Rust

### `cargo +nightly udeps`

**Finds:** unused dependencies declared in `Cargo.toml`.

**Invoke:** `cargo +nightly udeps --workspace` from the chunk root. Requires nightly toolchain — skip the tool if unavailable.

**Parse:** sections per crate listing `unused crates in the dependencies table` and `unused crates in the dev-dependencies table`.

**False positives:**
- Crates used only behind feature flags not enabled in the run.

### `cargo clippy -W dead_code`

**Finds:** dead functions, dead structs, dead enum variants.

**Invoke:** `cargo clippy --workspace --all-targets -- -W dead_code 2>&1`.

**Parse:** lines of form `warning: function ... is never used` with a `--> path/file.rs:LINE` follow-up.

**False positives:**
- `#[allow(dead_code)]`-marked items (clippy still surfaces them sometimes — confirm).
- Items only used in test builds.
