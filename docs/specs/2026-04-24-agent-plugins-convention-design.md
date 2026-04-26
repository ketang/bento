# agent-plugins Convention - Design

- Date: 2026-04-24
- Status: Draft
- Audience: plugin marketplace authors, plugin authors, and tool implementers across coding-agent ecosystems.

## Summary

The `agent-plugins` convention defines where coding-agent plugins look for user-editable customization files and how those files override plugin-bundled defaults.

For a logical customization file `<rel>` owned by marketplace `<marketplace>` and plugin `<plugin>`, lookup is:

1. repo scope
2. home scope
3. plugin-bundled default

Lookup is per file. The convention does not define install mechanics, file formats, cache/state/log locations, plugin discovery, or runtime-specific packaging.

This repository includes a first-class Python resolver at [reference/agent_plugins_resolver.py](reference/agent_plugins_resolver.py).

## Motivation

Some plugins expose editable templates, rules, allow lists, or other user-facing files. Without a shared convention, users may need to learn different locations and fallback behavior for each plugin, and plugin authors may duplicate similar lookup logic.

This convention is intentionally small: it standardizes only path layout, precedence, and resolution. It leaves install, seeding, packaging, cache, and runtime state to plugin or marketplace policy.

## Scope

This spec defines:

- Home-scope and repo-scope base directories.
- The `<marketplace>/<plugin>/<rel>` layout under each base.
- Per-file override precedence.
- Safe resolver behavior, including platform-specific home config roots.

This spec does not define:

- Cache files, mutable state, logs, or runtime files.
- Customization file formats.
- How directories or seed files are created.
- Plugin install systems, dependency resolution, discovery, or enablement.
- A cross-ecosystem plugin manifest.
- A system-wide scope such as `/etc/agent-plugins`.

## Terminology

- **Marketplace**: a named collection of plugins published together.
- **Plugin**: a unit of installation within a marketplace.
- **Customization file**: a user-editable file a plugin reads, often overriding a bundled default.
- **Plugin-bundled default**: the plugin's fallback content for a customization file. It may be an on-disk file, embedded content, or generated content.
- **Home scope**: the per-user, cross-repository customization location.
- **Repo scope**: the per-repository customization location for the current workspace.

## Base Directories

### Home Scope

Home-scope files live under:

```text
<home-config-root>/agent-plugins/
```

`<home-config-root>` is platform-specific:

- Linux, BSD, and other XDG-style systems: `$XDG_CONFIG_HOME` when set, otherwise `$HOME/.config`.
- macOS: `$XDG_CONFIG_HOME` when set, otherwise `$HOME/Library/Application Support`.
- Windows: `%APPDATA%` when set, otherwise `%USERPROFILE%\AppData\Roaming`.

Implementations MUST use the host platform's path APIs rather than string-building paths with a hard-coded separator. Examples in this document use `/` for readability.

### Repo Scope

Repo-scope files live under:

```text
<repo-root>/.agent-plugins/
```

`<repo-root>` is the current repository root. Plugins SHOULD use an agent-runtime-provided repository root when one exists. Otherwise, they SHOULD walk upward from the working directory and use the nearest ancestor containing a `.git` file or directory.

Why this matters: repo-scope overrides only work predictably when plugins agree on the same root. A runtime-provided root avoids ambiguity; the `.git` fallback keeps behavior consistent for ordinary Git worktrees, nested directories, and submodules. Plugins that use a different root-discovery rule MUST document it.

Repo-scope files may be committed when they are team policy, or gitignored when they are local clone policy. This convention does not choose for the repository.

## Path Layout

Within each base directory, plugin files live at:

```text
<base>/<marketplace>/<plugin>/<rel>
```

`<marketplace>` and `<plugin>` are the published identifiers. This revision assumes they are filesystem-safe path segments on every supported platform: no path separators, no reserved Windows device names, and no case-only distinctions. A marketplace that allows other names needs an escaping rule before claiming cross-platform support.

`<rel>` is a plugin-defined relative path below `<marketplace>/<plugin>/`. Plugins may use any internal structure under that point.

Example for marketplace `example`, plugin `widgets`, and file `rules.md`:

```text
<repo-root>/.agent-plugins/example/widgets/rules.md
<home-config-root>/agent-plugins/example/widgets/rules.md
```

Nested plugin structure is also valid:

```text
<repo-root>/.agent-plugins/example/widgets/handoff/template.md
<home-config-root>/agent-plugins/example/widgets/handoff/template.md
```

## Resolution

For any logical customization file `<rel>`, a plugin MUST consult candidates in this order and stop at the first existing regular file:

1. `<repo-root>/.agent-plugins/<marketplace>/<plugin>/<rel>`
2. `<home-config-root>/agent-plugins/<marketplace>/<plugin>/<rel>`
3. The plugin-bundled default for `<rel>`, wherever the plugin stores it.

This means:

- Repo scope overrides home scope and the bundled default.
- Home scope overrides the bundled default.
- A missing file falls through to the next scope.
- Lookup is per file, not per directory.

`<rel>` MUST be relative and MUST NOT escape the plugin root. Implementations should reject absolute paths, `..` traversal, and platform-specific root forms such as Windows drive paths.

If no candidate exists, the plugin treats the customization file as absent. This spec does not define plugin behavior for an absent optional file.

## Reference Resolver

The reference resolver is [reference/agent_plugins_resolver.py](reference/agent_plugins_resolver.py). It is executable and importable, has no third-party dependencies, and covers:

- Platform-specific home config roots.
- Repo-root discovery by `.git` file or directory.
- Candidate generation in spec precedence order.
- Regular-file resolution.
- Rejection of unsafe relative paths and unsafe identifier segments.

Plugins may port or wrap this code. They may cache a resolved path for a single invocation, but MUST NOT reorder precedence, skip scopes, or add automatic higher-priority scopes without documenting the deviation.

## Implementation Latitude

Plugin and marketplace authors may choose:

- How customization directories and seed files are created.
- Whether bundled defaults are files, embedded strings, or generated content.
- Whether repo-scope files are committed or gitignored.
- The file formats used for customization content.

These choices are conformant as long as lookup behavior matches this spec.

## Portability Requirements

Cross-platform adopters need to:

- Use the platform home config roots defined above.
- Use path APIs instead of hard-coded `/` paths.
- Treat `.git` as either a file or directory when discovering repo roots.
- Avoid identifier names that are illegal or ambiguous on Windows and case-insensitive filesystems, or define a reversible escaping rule.
- Test resolver behavior on at least one POSIX filesystem and one Windows path model.

The repo-scope directory name remains `.agent-plugins` on all platforms.

## Compatibility

This convention coexists with tool-specific directories such as `~/.claude/` and `~/.codex/`; those remain runtime-internal. It is also orthogonal to repo-root files such as `AGENTS.md`. Cache, state, logs, and runtime files remain outside this revision.

## Conformance

A plugin conforms if every user-editable customization file it resolves:

1. Uses `<marketplace>/<plugin>/<rel>` under the repo and home bases.
2. Resolves repo scope, then home scope, then bundled default.
3. Performs lookup per file.
4. Uses the platform home config root defined in this spec.
5. Rejects unsafe `<rel>` values that are absolute or escape the plugin root.

A marketplace conforms if it documents its published name and requires its plugins to conform individually. If its identifiers are not filesystem-safe path segments, it must also define an escaping rule.

No conformance test suite is part of this revision.
