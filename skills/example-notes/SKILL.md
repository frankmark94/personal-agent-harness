---
name: example-notes
description: Capture a quick note to the user's daily log. Use when the
  user says "note this", "remember that", or wants something jotted down
  without a full task.
---

# Quick notes

Append timestamped bullets to today's daily note.

## When to use

- "Note that the plumber is coming Tuesday."
- "Remember: I prefer morning meetings."

## When NOT to use

- Durable preferences → those go through the consolidation pass into
  MEMORY.md, not a raw note.
- Tasks with due dates → that's the scheduler's job.

## Workflow

1. Compute today's date in the user's timezone (from config).
2. Open `memory/YYYY-MM-DD.md`, creating it with the daily-notes
   template header if missing.
3. Append `- HH:MM — <note>` under a `## Notes` section.
4. Confirm with one short line; don't narrate the file mechanics.

## Example

User: "Note that the plumber is coming Tuesday."
→ appends `- 09:41 — Plumber coming Tuesday.` to today's note.
→ replies: "Noted."
