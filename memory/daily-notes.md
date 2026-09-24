# Daily notes convention

One file per day: `memory/YYYY-MM-DD.md`, in the user's timezone.

## Format

```markdown
# 2026-09-24

## Done
- Finished X; result was Y.

## Learned
- User prefers Z; corrected me on W.

## Open threads
- Waiting on Q before proceeding with P.
```

## Rules

- **Append-only during the day.** Never rewrite history; add new entries.
- **Facts, not prose.** Short bullets the consolidation pass can scan.
- **Quote corrections verbatim** when the user corrects you — that's
  the highest-signal content for future behavior.
- Timezone comes from config; filenames use the user's local date.
- Old notes are never deleted by the agent. Prune only on explicit
  user request (or a documented retention policy the user approved).
