---
name: react-vite-mantine
description: |
  Use when working in React/TypeScript/Vite projects that use Mantine. Starts
  by discovering the repo's actual frontend verification commands, component
  organization, theme conventions, and test helpers before applying stack
  conventions.
recommended_model: mid
---

# React + Vite + Mantine

## Model Guidance

Recommended model: mid.

Use a higher-capability model when the task crosses design-system boundaries,
theme architecture, or provider-heavy component behavior.

Use this skill when the project uses React, TypeScript, Vite, and Mantine.

## Discovery

Before changing components, styles, or tests, identify the repo's actual
frontend workflow:

- build, lint, test, and typecheck commands from `package.json`, `Makefile`,
  task runners, CI, `README`, and `AGENTS.md`
- where shared UI primitives, feature components, and page-level components
  live in this repo
- how the repo handles Mantine theming, CSS variables, and app-level providers
- which render helpers, test wrappers, or frontend fixtures the repo expects

Use repo-local commands and conventions when they exist. Treat the baseline
commands in this skill as a fallback, not as the default source of truth.

## Conventions

- Prefer Mantine layout components and style props
- Do not introduce Tailwind utility classes unless the repo already uses them
- Do not hardcode hex colors; use the repo's theme tokens or CSS variables
- Follow the repo's export style for components and hooks
- Put reusable UI components under the repo's existing shared UI component path
- Reuse the repo's app shell, provider, and theme setup instead of inventing a
  parallel pattern

## Testing

- Maintain the repo's frontend coverage expectations when they exist
- Add or update component tests when behavior changes
- Use the repo's shared render helpers when the component depends on Mantine,
  routing, state, or app-level providers
- If the repo uses visual, snapshot, or accessibility checks, keep those in the
  normal verification path

## Verification

Frontend changes require the repo's actual frontend verification gate. The
typical fallback baseline is:

```bash
pnpm build
pnpm lint
```

Run the repo's test and typecheck commands as well when the change affects
component behavior, state flow, or typed props.

## Guardrails

- Do not assume `pnpm` if the repo uses a different package manager.
- Do not introduce a new styling system when the repo already has a Mantine or
  CSS-variable pattern.
- Do not move components into a generic `ui` path unless that is how the repo
  is already organized.
- Do not skip provider-aware tests when the component depends on theme, routing,
  or app state.
