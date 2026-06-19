## Claude Code Requirements

The current runtime is **Claude**, so the counterpart reviewer is **Codex**.
Pass `--current-runtime claude` to both helper scripts.

- Cross path: `cross-check-run.py` invokes `codex exec --sandbox read-only`.
- Fallback path (Codex unavailable or the cross run exits `4`): dispatch an
  independent **same-runtime** reviewer with Claude Code's `Agent` tool, using a
  read-only toolset (`Read`, `Grep`, `Glob` only — never `Edit`/`Write`/`Bash`
  mutations). Give it the artifact and the matching
  `cross-check/references/prompts/review-<type>.md` prompt. It returns review
  text; pipe that into `cross-check-run.py ... --render-only --mode degraded`.
