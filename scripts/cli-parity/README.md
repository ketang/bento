# CLI argument-parity manifests

One JSON manifest per skill, consumed by [`scripts/check-cli-arg-parity`](../check-cli-arg-parity).

Each manifest lists the skill's **documented** CLI invocations so the checker can
assert that every documented command still carries the flags its `argparse`
parser marks `required=True` — the class of bug where a SKILL.md line drifts out
of sync with the script it invokes.

The manifest filename stem is the skill directory name under `catalog/skills/`.

```json
{
  "invocations": [
    {
      "doc": "SKILL.md",
      "command": "expedition/scripts/expedition.py close-task --expedition <name> --outcome kept|failed-experiment --summary <text>",
      "script": "scripts/expedition.py",
      "subcommand": "close-task"
    }
  ]
}
```

Fields (per invocation):

- `doc` — path, relative to the skill dir, of the SKILL.md / reference file that
  documents the command. The checker confirms `command` still appears there
  (normalized substring), catching manifest-vs-prose drift.
- `command` — the documented command text. May be copied verbatim from a
  multi-line fenced block; the checker normalizes backslash-newline
  continuations and whitespace before matching.
- `script` — path, relative to the skill dir, of the helper script.
- `subcommand` — the argparse subcommand name, or omit / `null` for
  single-command scripts.

Not every skill needs a manifest — only those whose docs show invocations of a
script that has `required=True` flags. Add an entry when you document a new
required-flag invocation.

## Coverage is enforced

You do not have to remember the rule above: the checker's `check_coverage` gate
scans every `catalog/skills/*/scripts/*.py` for `required=True` arguments and
fails if a documented (sub)command carrying a required flag has no manifest
entry here. So a new required-flag CLI with a documented invocation cannot
silently escape the parity check — CI points you at the missing entry.

Only *documented* (sub)commands are required to have coverage. An internal-only
required-flag subcommand that no `SKILL.md` / `references/*.md` tells an agent to
run carries no doc-drift risk and needs no manifest entry.

Known blind spots (documented in the checker's module docstring): the gate does
not catch doc prose *over-claiming* a flag as required when the parser does not,
and the AST walker does not resolve `add_mutually_exclusive_group()` or a parser
passed into a helper function. Both fail safe (under-report, never falsely fail).
