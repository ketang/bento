---
name: react-vite-mantine
description: |
  Use when working in React/TypeScript/Vite projects that use Mantine. Applies
  component, styling, testing, and verification conventions for that stack.
---

# React + Vite + Mantine

Use this skill when the project uses React, TypeScript, Vite, and Mantine.

## Conventions

- Prefer Mantine layout components and style props
- Do not use Tailwind utility classes
- Do not hardcode hex colors; use theme colors or CSS variables
- Use named exports
- Put reusable UI components under the project's UI component path
- Add a colocated test file for new components

## Verification

Frontend changes require the project's full frontend verification gate. The
typical baseline is:

```bash
pnpm build
pnpm lint
```

## Testing

- Maintain the project's coverage threshold
- Add tests for new components
- Use the project's shared render helpers when the component depends on Mantine
