---
name: dev-skill
description: Load and execute any Claude plugin skill from a local clone or GitHub repo URL. Use when QA-testing a skill before release, verifying a specific commit, or exercising a skill not yet published to the installed plugin cache.
---

# dev-skill

## When to use

Use in a target project session to test a skill from a local checkout or a
GitHub repo without modifying the installed plugin cache or the target project.
Works for any Claude plugin, not just bento.

## Inputs

Collect two inputs before proceeding:

1. **Source** — one of:
   - Absolute local path to a plugin checkout (e.g. `~/project/bento`,
     `/home/user/my-plugin`)
   - GitHub URL with optional ref:
     `https://github.com/<owner>/<repo>[@<ref>]`
     where `<ref>` is a commit hash, branch, or tag. Defaults to `main` when
     omitted.

2. **Skill name** — the skill directory name within the plugin
   (e.g. `swarm`, `handoff`, `launch-work`).

Reject any skill name that contains path separators (`/`, `\`) or `..`.

## Path resolution

### Local source

Try candidate paths in order:

1. `<source>/catalog/skills/<name>/SKILL.md` — bento canonical layout
2. `<source>/skills/<name>/SKILL.md` — standard plugin layout

Stop at the first path that resolves. If neither exists, report both paths
tried and stop.

### GitHub source

Parse `<owner>`, `<repo>`, and `<ref>` from the URL. If no `@<ref>` is
present, use `main`.

Fetch candidate raw URLs in order via WebFetch:

1. `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/catalog/skills/<name>/SKILL.md`
2. `https://raw.githubusercontent.com/<owner>/<repo>/<ref>/skills/<name>/SKILL.md`

A non-200 response means the candidate does not exist; try the next. If both
fail, report the URLs tried and their HTTP status codes, then stop.

## Script detection

After loading the SKILL.md content, check whether it contains any reference to
a `scripts/` path (simple substring match on the string `scripts/`).

If the source is a GitHub URL and scripts are referenced, warn before executing:

> "This skill references helper scripts at `scripts/`. Scripts cannot be
> executed from a GitHub source — only the markdown instructions will run. For
> full-fidelity testing including script execution, clone the repo locally and
> point dev-skill at the local path."

Continue execution after the warning. Do not block.

## Execution

Announce before following the skill content:

> "Loading skill `<name>` from `<resolved-path>`."
> "Base directory: `<base-directory>`"

The **base directory** is:

- Local: the directory containing the resolved SKILL.md
  (e.g. `~/project/bento/catalog/skills/swarm/`)
- GitHub: the raw URL prefix up to and including the skill directory
  (e.g. `https://raw.githubusercontent.com/ketang/bento/main/catalog/skills/swarm/`)

Follow the loaded skill content as active instructions, exactly as if it had
been loaded by the `Skill` tool. Resolve all relative script paths against the
base directory.

## Non-negotiable rules

- Do not modify the installed plugin cache.
- Do not modify any file in the target project as part of dev-skill setup.
- Always announce the resolved source path and base directory before executing.
- Always surface the script warning before executing when applicable.
- Do not fabricate a skill path. If resolution fails, report what was tried.
- Reject skill names containing `/`, `\`, or `..`.
