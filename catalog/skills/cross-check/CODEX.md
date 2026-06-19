## Codex Requirements

The current runtime is **Codex**, so the counterpart reviewer is **Claude**.
Pass `--current-runtime codex` to both helper scripts.

- Cross path: `cross-check-run.py` invokes `claude -p --output-format json
  --tools "Read,Grep,Glob" --permission-mode dontAsk`.
- Fallback path (Claude unavailable or the cross run exits `4`): dispatch an
  independent **same-runtime** reviewer with Codex sub-agents (`spawn_agent`,
  then `wait_agent`), running read-only. Give it the artifact and the matching
  `cross-check/references/prompts/review-<type>.md` prompt. It returns review
  text; pipe that into `cross-check-run.py ... --render-only --mode degraded`.
