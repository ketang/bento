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
