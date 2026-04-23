# Dependency Bootstrap

After entering the linked worktree, install build/runtime dependencies so the
first build, test, or typecheck command does not fail on missing packages.

## Detection

Prefer the repo's documented bootstrap command (Makefile target, `justfile`,
`scripts/bootstrap`, CONTRIBUTING) when one exists. Otherwise detect by
lockfile and run the matching installer:

| Lockfile / marker                | Command                                  |
|----------------------------------|------------------------------------------|
| `pnpm-lock.yaml`                 | `pnpm install --frozen-lockfile`         |
| `yarn.lock` + `.yarnrc.yml`      | `yarn install --immutable`               |
| `yarn.lock` (classic)            | `yarn install --frozen-lockfile`         |
| `package-lock.json`              | `npm ci`                                 |
| `bun.lockb`                      | `bun install --frozen-lockfile`          |
| `go.sum`                         | `go mod download`                        |
| `Cargo.lock`                     | `cargo fetch`                            |
| `uv.lock`                        | `uv sync --frozen`                       |
| `poetry.lock`                    | `poetry install --no-root`               |
| `Pipfile.lock`                   | `pipenv sync`                            |
| `requirements*.txt` (no lock)    | `pip install -r <file>` in a venv        |
| `Gemfile.lock`                   | `bundle install`                         |
| `composer.lock`                  | `composer install`                       |
| `mix.lock`                       | `mix deps.get`                           |
| `flake.lock` / `shell.nix`       | `nix develop` or `nix-shell`             |

If multiple apply (monorepo), install each. If none apply and no documented
bootstrap exists, skip this step and note it in the task summary.

## Disk Usage On ext4

ext4 has no reflink support, so each worktree pays full cost for anything
copied into it. Mitigations:

- **JavaScript**: pnpm hardlinks from a central store
  (`~/.local/share/pnpm/store`) into each `node_modules`, so additional
  worktrees cost little. Yarn Berry with `nodeLinker: pnpm` behaves similarly.
  npm and classic yarn duplicate the full tree per worktree — accept the cost
  or migrate the repo to pnpm.
- **Go, Rust, Python, Ruby**: the global module/crate/wheel/gem caches
  (`$GOMODCACHE`, `~/.cargo`, uv/pip caches, `~/.bundle`) are already shared
  across worktrees. Prefer to leave these at their defaults; overriding them
  to per-worktree paths defeats the sharing and should only be done when the
  repo documents a specific reason.
- **Virtualenvs / `node_modules` / `target/` build outputs**: inherently
  per-worktree on ext4. Remove stale worktrees promptly via `closure` rather
  than hoarding them.

## Failure Handling

If the install command fails, surface the error and stop. Do not proceed to
implementation against a half-installed tree.
