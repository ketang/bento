# agent-plugins Convention — Design

- Date: 2026-04-24
- Status: Draft
- Audience: plugin marketplace authors, plugin authors, and tool implementers across agent ecosystems (Claude Code, Codex, and any future agent runtime that loads plugin bundles).

## Summary

The `agent-plugins` convention defines where plugins that ship with coding-agent marketplaces store user-editable customization files on the filesystem, and how those user-edited files compose with plugin-bundled defaults.

The convention is cross-marketplace and agent-neutral. It describes only the directory layout, override precedence, and lookup algorithm. It does not mandate how directories or files get created, what file formats are used, or how plugins are installed.

## Motivation

Plugins frequently expose user-editable artifacts: prompt templates, rule lists, allow/deny lists, fill-in-the-blank content skeletons, personalization overrides. Today, each plugin chooses its own location for these files ad hoc. The consequences:

- Users who install plugins from multiple marketplaces get an inconsistent scatter of customization paths to learn and back up.
- Plugin authors write one-off discovery logic for their customization files instead of following a shared convention.
- There is no shared vocabulary for "the file the user can edit" versus "the default the plugin ships with."
- Override semantics are inconsistent across plugins, making multi-scope (home vs repo) customization unpredictable.

A small, focused convention solves the layout and lookup pieces without reaching into the orthogonal questions of cache, runtime state, install mechanics, or packaging.

## In Scope

This spec covers, for a given plugin:

1. The directory path where user-editable customization files live at home scope.
2. The directory path where user-editable customization files live at repo scope.
3. The per-file override precedence across repo scope, home scope, and plugin-bundled defaults.
4. The lookup algorithm a plugin MUST use when resolving a customization file.

## Out of Scope

Explicitly not covered:

- Cache files, mutable state, logs, runtime/ephemeral files. These may be addressed by a later extension or deferred to established conventions such as the XDG Base Directory specification.
- File formats for customization files. Each plugin chooses its own.
- How user-editable directories and their seed files get created. Installers, session-lifecycle hooks, first-use self-healing, and manual user setup are all conformant.
- Plugin install systems, dependency resolution, or packaging.
- Plugin discovery or enablement mechanics within an agent runtime.
- Naming or uniqueness rules for marketplace or plugin identifiers. The convention defers to the marketplace's own published names.

## Non-Goals

- Replacing tool-specific dotdirs such as `~/.claude/` or `~/.codex/`. Those remain tool-internal and are not touched by this convention.
- Defining a cross-ecosystem plugin manifest or package format.
- Prescribing a runtime data directory analogous to XDG `data`, `cache`, or `state`. This spec is focused on user-editable configuration only.

## Terminology

- **Marketplace**: a named collection of plugins published together. The marketplace's published name is the identifier used in paths.
- **Plugin**: a unit of installation within a marketplace. The plugin's published name within its marketplace is the identifier used in paths.
- **Customization file**: a file the user is expected to read and edit, typically overriding a plugin-bundled default.
- **Plugin-bundled default**: a file shipped inside the plugin bundle that the plugin reads when no user override is present. Its on-disk location inside the bundle is internal to the plugin and unspecified here.
- **Home scope**: the per-user, cross-repository location for customization files.
- **Repo scope**: the per-repository location for customization files, scoped to the repository a user is currently working in.

## Base Directories

### Home scope

The home-scope base directory is:

```
$XDG_CONFIG_HOME/agent-plugins/
```

When `XDG_CONFIG_HOME` is unset or empty, the default per the XDG Base Directory specification applies: `$HOME/.config`. The home-scope base directory then resolves to:

```
$HOME/.config/agent-plugins/
```

Plugins MUST honor `XDG_CONFIG_HOME` when it is set. On platforms where XDG is not conventionally followed, plugins MAY fall back to `$HOME/.config/agent-plugins/` directly; documenting platform-specific deviations in the plugin's own documentation is encouraged but not required.

### Repo scope

The repo-scope base directory is:

```
<repo-root>/.agent-plugins/
```

Where `<repo-root>` is the root of the repository a user is currently working in.

Plugins SHOULD determine `<repo-root>` by using the repository root reported by the agent runtime when the runtime exposes one (for example, through an environment variable set by the agent), and otherwise SHOULD use the nearest ancestor directory of the agent's working directory that contains a `.git` entry. Plugins MAY deviate from this guidance when they target an ecosystem where neither signal is available, but they MUST document the deviation.

Why this matters: if two plugins operating in the same workspace disagree on `<repo-root>`, they will read from different `.agent-plugins/` directories and produce different customization behavior for files the user thought were in one canonical place. A user who places a customization file at what they believe is "the repo root" expects every plugin in that workspace to see it. Divergence is silent, hard to reproduce, and erodes the user's mental model that the convention is stable. A shared root-discovery rule collapses the space of reasonable interpretations down to one per workspace in practice, even when different plugins are written by different authors. Agent runtimes that expose an authoritative project-root signal should be preferred because they remove ambiguity in edge cases such as nested repositories, detached work trees, submodules, and invocations from outside the working tree.

Repo-scope files that are intended to be checked into version control SHOULD be committed by the repository's maintainers. Repo-scope files that are intended to be local to a single clone MAY be listed in `.gitignore`. The convention does not mandate either choice.

## Path Layout

Within each base directory, customization files for a given plugin live under a two-level path:

```
<base>/<marketplace>/<plugin>/...
```

- `<marketplace>` is the marketplace's published name.
- `<plugin>` is the plugin's published name within that marketplace.
- Below the `<plugin>` level, each plugin defines its own internal structure. The convention does not prescribe a third level such as "skill" or "component"; plugins that have internal substructure are free to model it however they wish.

A plugin identified by marketplace `example` and plugin name `widgets`, with an internal customization file named `rules.md`, would store that file at:

- Repo scope: `<repo-root>/.agent-plugins/example/widgets/rules.md`
- Home scope: `$XDG_CONFIG_HOME/agent-plugins/example/widgets/rules.md` (default `~/.config/agent-plugins/example/widgets/rules.md`)

A plugin with nested customization — for example a customization file for its `handoff` feature — would store it at:

- Repo scope: `<repo-root>/.agent-plugins/example/widgets/handoff/template.md`
- Home scope: `$XDG_CONFIG_HOME/agent-plugins/example/widgets/handoff/template.md`

The path segment structure below `<plugin>` is entirely at the plugin's discretion. The convention constrains only `<base>/<marketplace>/<plugin>/` as the root per plugin.

## Override Precedence

For any logical customization file identified by a relative path `<rel>` underneath `<marketplace>/<plugin>/`, plugins MUST resolve it by consulting candidate locations in the following order, stopping at the first existing regular file:

1. `<repo-root>/.agent-plugins/<marketplace>/<plugin>/<rel>`
2. `$XDG_CONFIG_HOME/agent-plugins/<marketplace>/<plugin>/<rel>` (default `~/.config/agent-plugins/<marketplace>/<plugin>/<rel>` when `XDG_CONFIG_HOME` is unset)
3. The plugin-bundled default for `<rel>`, at whatever path the plugin uses internally.

This ordering means:

- A repo-scope file overrides any home-scope file and the plugin-bundled default.
- A home-scope file overrides the plugin-bundled default.
- Absence of a file at a given scope falls through to the next scope; it does not cause an error.

Lookup is **per file**, not per directory. A user who wants to override a single file does not have to copy the entire customization directory; they create only the file they want to override at the scope they want it to apply to. Any files not present at a given scope continue to resolve through the fallback chain.

If none of the three candidates exists, the plugin MUST treat the file as absent and behave accordingly per its own semantics. The convention does not prescribe what "absent" means to any particular plugin.

## Lookup Algorithm

A reference implementation, in pseudocode:

```
def resolve(marketplace, plugin, rel_path, repo_root, bundled_default_path):
    candidates = []
    if repo_root is not None:
        candidates.append(
            os.path.join(repo_root, ".agent-plugins", marketplace, plugin, rel_path)
        )
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    candidates.append(
        os.path.join(xdg_config_home, "agent-plugins", marketplace, plugin, rel_path)
    )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    if bundled_default_path is not None and os.path.isfile(bundled_default_path):
        return bundled_default_path
    return None
```

Plugins MAY optimize this (for example, caching the resolved path for the lifetime of a single invocation). They MUST NOT reorder precedence, skip scopes, or introduce additional scopes that take effect automatically without documenting the deviation.

## Implementation Latitude

The convention is deliberately silent on several implementation questions. Plugin and marketplace authors are free to choose:

- **How customization directories and seed files get created.** A plugin may ship an installer that populates the home-scope directory, use an agent's session-lifecycle hook to seed it on first session after install, self-heal the directory on first use when a file is missing, or simply instruct users to create files manually. All are conformant.
- **Whether plugin-bundled defaults are shipped on disk or compiled in.** The convention refers to "the plugin-bundled default" as a logical fallback. Whether that default is a file inside the plugin bundle, an embedded string in plugin code, or generated dynamically is not this spec's concern.
- **Repo-scope inclusion in version control.** Teams may commit repo-scope customizations to share them across collaborators, or gitignore them to keep them local. The convention does not prescribe either.
- **File formats.** The convention applies equally to Markdown templates, TOML, YAML, JSON, plain text, or any other format a plugin chooses.

## Compatibility with Existing Conventions

- **XDG Base Directory specification.** The home-scope base directory honors `XDG_CONFIG_HOME` and falls back to `~/.config` when unset, matching XDG semantics for the `config` category. This spec does not address XDG `data`, `cache`, `state`, or `runtime` directories; plugins with files that fit those categories should follow XDG for them independently of this convention.
- **Tool-specific dotdirs.** Plugins MAY continue to read from and write to `~/.claude/`, `~/.codex/`, or other tool-specific locations as required by the agent runtime they target. This convention does not preempt those; it adds an agent-neutral location for user-editable plugin customizations specifically.
- **AGENTS.md and similar repo-root files.** This convention is compatible with and orthogonal to conventions like `AGENTS.md`. Single-file repo conventions continue to live at the repo root; this spec governs a directory tree under `<repo-root>/.agent-plugins/` for plugin-specific files.

## Future Extensions

The following are explicitly left to future revisions or companion specs:

- A parallel convention for cache, mutable state, logs, or runtime files (potentially aligning directly with XDG `cache`, `state`, and `runtime` categories).
- A normative appendix on recommended seeding mechanisms (installer scripts, session hooks, first-run self-heal) and their trade-offs.
- A system-scope directory (for example, `/etc/agent-plugins/` on Linux) for multi-user machines, CI base images, and container base layers.
- Machine-readable metadata for advertising which files a plugin reads from the customization tree.

Adopters SHOULD NOT depend on any of these being specified in the future; if they need them now, they should solve them in a plugin- or marketplace-local way until the convention is extended.

## Conformance

A plugin conforms to this specification if, for every file it treats as a user-editable customization:

1. It looks the file up under `<marketplace>/<plugin>/<rel>` where `<marketplace>` and `<plugin>` are the plugin's published identifiers.
2. It consults the repo-scope base first, then the home-scope base, then any plugin-bundled default, in that order.
3. It performs lookup per file rather than per directory.
4. It honors `XDG_CONFIG_HOME` for the home-scope base, falling back to `$HOME/.config` when unset.

A marketplace conforms if it documents its published name and requires its plugins to conform individually.

No conformance test suite is part of this revision.
