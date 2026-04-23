# Primary Branch Sync Overlay For Closure

Use this overlay only when the repo explicitly wants the local primary branch to
be synced before cleanup analysis.

Treat `<primary-branch>` as the branch detected in the core skill.

## Sync Procedure

1. Check out the primary branch:
   ```bash
   git checkout <primary-branch>
   ```
2. Fast-forward from origin:
   ```bash
   git pull --ff-only origin <primary-branch>
   ```
3. Push only if the project explicitly expects local cleanup to publish the
   synchronized branch:
   ```bash
   git push origin <primary-branch>
   ```

## Safety

- If the pull fails due to divergence, stop and report.
- Do not force-push or rebase the primary branch without explicit approval.
- Running quality gates on the primary branch does not imply that fixes should
  be committed there automatically.
