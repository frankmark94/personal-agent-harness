# SKILL.md spec

A skill is a reusable workflow: a directory containing a `SKILL.md`
with YAML frontmatter, plus any supporting scripts.

## Frontmatter

```yaml
---
name: web-search
description: Search the public web for current information; use when the
  answer may have changed since training or needs a source.
---
```

- `name`: unique slug, matches the directory name.
- `description`: keyword-rich. This is what discovery searches —
  write it for the *triggering situation*, not just the capability.

## Body

Markdown instructions the agent follows when the skill is loaded:

1. When to use / when NOT to use (boundaries matter more than features).
2. Step-by-step workflow.
3. Worked example.
4. Failure modes and what to do instead.

Keep it short enough to fit in context alongside the task. Supporting
scripts live next to `SKILL.md`; relative paths resolve against the
skill's own directory so skills stay portable.

## Lifecycle

- **Author:** when a workflow recurs and works, write it up as a skill.
- **Audit:** periodically check skills are still accurate; fix or retire.
- **Retire:** delete skills that stopped working or were superseded.
