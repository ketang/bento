# compress-docs: Compression Rules

This reference governs how the model writes the compression plan. Every
rule here is binding: violations are plan-quality bugs, not style issues.

## Reason-code taxonomy

Every proposed change in the plan must cite exactly one reason code from
this list. Free-form narrative reasons are not allowed.

| Code | Meaning |
|------|---------|
| `duplicate` | Content appears verbatim or near-verbatim in another in-scope file. Cite the other file. |
| `dead-ref:<target>` | Content references a path, command, file, or symbol that does not exist. Cite the target. |
| `verbose` | Content is correct but longer than it needs to be. Rewrite, do not delete. |
| `outdated` | Content describes a state of the world that no longer holds. Delete. |
| `contradicted-by:<file>` | Content conflicts with a newer or higher-priority file. Cite the conflicting file. |
| `merge-target:<file>` | Content is being relocated into another file to reduce duplication. Cite the target. |

## Preserved-claims list

Every file section in the plan must begin with a **Preserved claims**
list. This is the model's explicit inventory of the distinct rules,
facts, conventions, and commitments the file contains, regardless of
whether the model proposes to touch them.

Purpose: the reviewer checks the list against the post-apply diff. If a
claim in the list does not appear in the post-apply file, that is a
regression — the compression dropped load-bearing content.

Requirements for the list:

1. One bullet per distinct claim. If the source file states the same
   rule twice, list it once.
2. Each bullet is a short noun phrase or declarative sentence. Not a
   quote.
3. Group related claims together for easy visual scanning.
4. If a file has no load-bearing claims (e.g., a `MEMORY.md` index that
   only contains pointers), say "Preserved claims: none (file is an
   index — content is preserved by preserving the pointers)."

## Diff format

Every proposed change must include a literal before/after diff, not a
summary. Use fenced `diff` code blocks with `-` and `+` line prefixes.

Summary reasons ("compress this section", "tighten the wording") are
not acceptable substitutes for the actual text.

## Verbose vs. outdated vs. wrong

The model must distinguish three failure modes:

- **Verbose:** the content is true but long. The compressed version
  must preserve every distinct claim from the original. Use the
  `verbose` reason code.
- **Outdated:** the content was true but no longer is. The compressed
  version drops the claim. Use the `outdated` reason code. Requires
  explicit evidence — a dead reference, a contradiction with newer
  content, or a rule the user has explicitly retired.
- **Wrong:** the content was never true. Out of scope for this skill.
  Flag it in the plan summary but do not include it in the change list.

The preserved-claims list exists specifically to keep the model honest
about which category it is in. When compressing verbose content, the
preserved-claims list remains unchanged; when deleting outdated content,
the corresponding claim disappears from the list and the deletion is
documented.

## Tier-level approval

The plan groups changes under four tier headings (Project, Referenced,
User-global, Memory). The user approves each tier independently by
ticking a checkbox at the bottom of the plan file. Unticked tiers are
skipped entirely. Files within an approved tier can be skipped
individually by adding `<!-- skip -->` next to the file heading.

The model's job at plan-writing time is to produce the plan in this
shape. The model's job at apply-time is to respect the checkboxes and
skip markers exactly.
