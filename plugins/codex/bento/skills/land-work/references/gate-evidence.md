# Binding Gate Evidence

`land-work` must not land a branch without proof the repo's own standard gates
pass on the exact merge candidate — regardless of which merge path lands it.

## Discover the gate suite

Reuse the discovery approach the stack skills (`go-pgx-goose`,
`react-vite-mantine`) and `generate-audit`'s `audit-discover.py` use: read the
repo's actual command surface instead of inventing commands. Check, in priority
order:

- Task runners: `Makefile`, `justfile`, `Taskfile.yml` (e.g. `make test`,
  `make lint`, `make check`) — prefer the repo's own wrapper targets.
- Language/tool manifests: `package.json` scripts, `pyproject.toml`/`tox.ini`,
  `Cargo.toml`, and similar.
- Documented commands in `CLAUDE.md`, `AGENTS.md`, `README`, or `CONTRIBUTING`
  (a "standard gate suite", "before you commit", or "CI runs" section).
- CI config under `.github/workflows/*.yml` (or other CI): the jobs that gate
  merges name the canonical commands.
- Anywhere else the repo documents its required checks.

Treat the union of what these sources call required as the gate suite. Prefer a
single documented aggregate target (e.g. `make test-standard`) when one exists.
Because discovery spans this many surfaces, "no gate suite discovered" should be
rare — reach it only after checking all of them.

## Run against the exact candidate

Run the suite against a clean checkout of the leased base SHA with the branch
applied — the step 8 merge preview is exactly this. Do not run against the
shared primary checkout, which may hold other agents' state. Verification is
valid only for the candidate it ran on: a later rebase, merge, or conflict
resolution makes it stale.

## Pre-existing red primary branch

Before landing, the primary branch must be green. If a gate fails, re-run that
gate on the bare leased base (no branch applied) to tell the two cases apart:

- **fails on the bare base too** → pre-existing red. Stop: do not stack work on
  a red base. Report it, file or associate a tracker issue for the breakage,
  and get direction.
- **passes on the bare base, fails with the branch** → the branch caused it.
  Fix it on the branch before landing.

## Waiver

Merge only on green, or with an explicit user-approved waiver. The waiver must
state which gate is waived, why, and what protection is lost. Record it in the
tracker issue for this work (issue comment or notes) BEFORE the merge — an
unrecorded waiver is not a waiver. This pre-merge waiver note is the one tracker
mutation allowed before verified landing, an intentional carve-out from the
mutate-only-after-landing rule in `workflow-invariants.md`; do not close or
otherwise advance the issue until the work has landed. Do not waive on your own
authority.

## Closure-note evidence

The closure note must record evidence, not assertion. For each gate include the
exact command and its exit status, for example:

    make test  → exit 0
    make lint  → exit 0
    make build → exit 0

For a waived gate, name it and link the tracker issue where the waiver is
recorded. When no suite was discoverable, state that ("no repo gate suite
discovered; none run"). "Tests pass" without commands and exit statuses is not
evidence.
