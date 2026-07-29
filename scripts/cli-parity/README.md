# CLI argument-parity manifests

One JSON manifest per skill, consumed by [`scripts/check-cli-arg-parity`](../check-cli-arg-parity).

Each manifest lists the skill's **documented** CLI invocations so the checker can
assert that documented usage and the `argparse` parser agree — the class of bug
where a SKILL.md line drifts out of sync with the script it invokes. Two
directions are checked:

- **under-claiming** — a flag the parser marks `required=True` is missing from
  the documented command;
- **over-claiming** — the doc annotates a flag `(required)` (e.g.
  ``` `--target` (required) ```) that the parser never marks `required=True`. A
  flag required by *any* of the script's parsers satisfies the check, so a flag
  required on one subcommand and optional on another is not reported. Describe
  runtime-validated flags in prose instead of annotating them `(required)`.

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
script that has `required=True` flags, or whose docs carry `(required)`
annotations. Add an entry when you document a new required-flag invocation.

## Parser patterns

Introspection is static (AST), so it models only the parser shapes the catalog
uses: `ArgumentParser(...)`, `add_subparsers(...)`, `add_parser(...)`, and
`add_argument(...)` on a variable bound to one of those. Two patterns are
**hard errors** rather than silent skips, because skipping would under-report
required flags and turn the check green on real drift:

- `add_mutually_exclusive_group()` / `add_argument_group()` containers;
- `add_argument(...)` called on a function *parameter* (a helper that receives
  the parser).

If a script needs one of these, extend the walker in
[`scripts/check-cli-arg-parity`](../check-cli-arg-parity) to model it — do not
loosen the error.
