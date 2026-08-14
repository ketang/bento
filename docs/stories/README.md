This directory stores intent stories — structured, prose-form records of how users invoke and experience bento skills. Stories are written in observed mode (from actual usage) or accepted mode (validated with users). They serve as the authoritative source for behavioral fidelity checks across skill iterations.

## Why stories here omit `Evidence.Surface`

Bento's user-facing surfaces are agent skills — markdown capabilities invoked
by name (`bento:launch-work`) rather than CLI commands, HTTP routes, or package
binaries. storystore's surface inventory extracts only TypeScript/JavaScript
CLI commands, HTTP routes, package bins, exports, test names, migration schema
columns, and H2/H3 headings from root `README.md`/`DESIGN.md`/`ARCHITECTURE.md`.
No extractor recognizes an agent skill, so a `skill: <name>` ref is unparseable
and a `cli: <name>` ref never resolves against this repo's inventory. Every
story declaring one produced a `surface-missing` finding, which in turn blocked
`stories-update`'s guarded-edit workflow for the whole corpus.

Rather than re-express skills under a kind that does not describe them, these
stories omit the optional `Evidence.Surface` subsection. The information is not
lost: each story's slug and title name the skill, and `Evidence.Docs` points at
`catalog/skills/<name>/SKILL.md` and its references. `stories-impact-check`
already matches on doc-evidence paths and description tokens, so skill edits
still surface the affected stories. Third-party CLIs some stories rely on
(`bd`, `gh issue`, `make demo`) are described in the story prose, where they
belong — they are dependencies of the workflow, not surfaces this repo exposes.

Add a `Surface` subsection back only for a genuinely extractable surface, or
after storystore grows an agent-skill surface kind.
