# Consolidation pass

A scheduled job (e.g. hourly, only when there is new signal) that turns
raw activity into durable memory.

## What it does

1. Read recent daily notes + recent conversation since the last pass.
2. Extract candidate durable facts: preferences stated, corrections
   made, commitments promised, people/groups mentioned repeatedly.
3. Update `MEMORY.md` (Facts / Preferences / Commitments) and the
   relevant `people/` / `groups/` pages.
4. Record what was promoted in today's note, so the next pass doesn't
   re-process it (a `last_consolidated` watermark).

## Rules

- **Promote upward only.** Daily notes are append-only; consolidation
  never edits or deletes them.
- **Corrections win.** If the user corrected the agent, the correction
  replaces the old fact — note the replacement, don't keep both.
- **Confidence by repetition.** One mention = note it in the daily
  log; repeated or explicit ("always do X") = promote to MEMORY.md.
- **Keep MEMORY.md tight.** If a fact stops being true, remove it —
  stale memory is worse than no memory.
- **People pages are personal.** Never copy them into anything shared
  (reports, skills, prompts for other users).

## Sketch

The nightly version of this pass is implemented in `agent/dream.py`:
it reflects over the day's notes and MEMORY.md, saves a dated report
to `memory/dreams/YYYY-MM-DD.md`, and appends only deduplicated
`@@UPDATE@@` one-liners to MEMORY.md (never destructive). Still future
work: the frequent (hourly) watermark-based pass with people/group page
updates and a `last_consolidated` watermark.
