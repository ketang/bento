---
name: bugshot
description: Launch a screenshot gallery for visual bug review and issue filing
arguments:
  - name: directory
    description: Path to the directory containing screenshots
    required: true
---

# Bugshot — Screenshot Bug Filing Skill

Review screenshots in a browser gallery and file issues from user comments.

## Startup

1. Validate that `{{directory}}` exists and contains at least one recognized file. Recognized extensions are defined in `gallery_server.py:IMAGE_EXTENSIONS` and `ANSI_EXTENSION` (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.ansi`).
2. Find the bugshot installation directory (the directory containing this `SKILL.md`).
3. Run the CLI with `--json` and capture both stdout and stderr:

```bash
python3 {{bugshot_dir}}/bugshot_cli.py --json {{directory}}
```

4. Read the first line of the CLI's stderr — it is `Gallery is running at <url>`. In an interactive agent session, immediately print this URL in the visible conversation even if the CLI is running as a background command. Tell the user:

   > Bugshot gallery is running at `<url>`. Open that URL, review the screenshots, type comments on any issues you see, then click "Done Reviewing".

   The gallery binds to `0.0.0.0` by default, so the URL is reachable from other hosts on the network. If the user wants loopback only, pass `--local-only`.

5. Wait for the CLI to exit. The CLI handles all polling, heartbeat timeout, and browser lifecycle internally. Do not poll any HTTP endpoints yourself.

## Process Comments

The CLI's stdout ends with a single JSON line:

```json
{"draft_count": 2, "drafts": [
  {"image_name": "login-page.png", "image_path": "/abs/path/login-page.png",
   "user_comment": "Submit button is clipped"},
  ...
]}
```

If `draft_count` is `0`, report "No comments were submitted." and stop.

For each draft:

**a. Examine the screenshot.** Read the image at `image_path` using your vision capability. Identify:
- What screen/page/view is shown
- What UI elements are relevant to the user's comment
- What specifically appears wrong or unexpected

**b. Compose the issue.** Combine the user's comment with your visual analysis. If the project has issue templates, follow them. Otherwise use this structure:

```
## Current Behavior
[What is happening, based on the screenshot + user's comment]

## Expected Behavior
[What should happen instead, inferred from context]

## Screenshot Description
[Detailed description of the screenshot, sufficient without the image]

## Additional Context
- Screenshot: <image_name>
- User comment: "<user_comment>"
```

**c. Check for duplicates.** If the project has an issue-flow skill, use its search capability with keywords from the composed issue. Present any potential duplicates before filing:

> Found potential duplicates:
> - #42: "Login button overflow on mobile" (open)
> - #31: "Submit button CSS issue" (closed)
>
> File anyway, or skip?

If there is no issue-flow skill available, skip duplicate checking.

**d. Confirm with the user.** Show the composed issue:

> **Filing issue for `login-page.png`:**
> [composed issue text]
>
> File this issue?

If the user says no, allow them to edit or skip.

**e. File the issue.** Delegate to the project's issue-flow skill. If no such skill is available, tell the user the issue is ready and ask where to file it (or write it to a file).

**f. Attach the screenshot.** If the tracker supports attachments, attach the file at `image_path`. If attachment fails, report concisely:

> Note: Could not attach screenshot to #42 (attachment not supported by tracker).

**g. Report.**

> Filed: #42 — "Login submit button is clipped on right edge"

After all drafts are processed:

> Bugshot session complete. Filed N issues, skipped M.

## Error Handling

- If the CLI exits non-zero, report the contents of its stderr and stop.
- If the stdout doesn't end with a parseable JSON line, report the CLI output verbatim and stop.
- If an issue fails to file, report the error and continue with the remaining drafts.
