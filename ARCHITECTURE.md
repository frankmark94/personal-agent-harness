# Architecture

How the pieces of a persistent personal AI agent fit together.
Each section maps to code or docs elsewhere in this repo.

## 1. Tool-calling LLM as the reasoning core (provider-agnostic)

The model does one thing: given a conversation (system prompt, history,
tool definitions, tool results), it either replies with text or emits
tool calls. It never touches the world directly — every effect goes
through a tool.

Provider-agnostic means: talk to any **OpenAI-compatible chat completions
API**. The loop sends `messages` + `tools` (JSON Schema function
definitions) and parses `tool_calls` from the response. Swapping providers
is a config change, not a code change. See `agent/loop.py`.

## 2. Agent runtime loop: reason → act → observe

```
while True:
    response = model.chat(messages, tools)   # REASON
    if response has tool_calls:
        for call in response.tool_calls:
            approvals.check(call)            # gate consequential actions
            result = registry.run(call)      # ACT
            messages.append(tool_result)     # OBSERVE
    else:
        break  # final answer to the user
```

The loop is deliberately dumb. All judgment lives in three places: the
system prompt (behavior), the tool definitions (capabilities), and the
approval policy (safety). Keep the loop small so it stays auditable.

## 3. Persistent per-user compute

The agent runs on a machine that **outlives any single conversation**:
a VM or container per user with a real filesystem, a shell, and the
ability to run background processes. Consequences:

- Files written today are readable tomorrow (`memory/`, workspace).
- Scheduled jobs and long-running processes keep running with no chat open.
- Tool state (browser sessions, logins, caches) persists.

Design rule: anything that must survive a restart lives under the
workspace directory, never in process memory. Treat `/tmp` and anything
outside the workspace as ephemeral.

## 4. Scheduler: cron-like jobs + event hooks

Two kinds of background work:

- **Cron-like recurring jobs.** A persistent job list (e.g. JSON on disk):
  each job has a schedule expression, a prompt/task, and last-run state.
  A poller wakes up, finds due jobs, and injects their task into the
  agent loop as a fresh turn. Jobs must be idempotent — assume they can
  run twice.
- **Event hooks.** "When X happens, do Y": a new email arrives, a file
  changes, a webhook fires. Hooks are scripts or job definitions with a
  trigger instead of a schedule. Time-based and event-based are kept
  separate because their failure modes differ (missed run vs. missed
  event need different recovery).

See `scheduler/`.

## 5. File-backed memory

Memory is **plain Markdown files**, not a database. Three layers:

- `MEMORY.md` — curated, durable facts: who the user is, standing
  preferences, commitments. Kept tight; promoted only what lasts.
- `memory/YYYY-MM-DD.md` — dated daily notes: raw detail of what happened.
- `memory/people/<name>.md`, `memory/groups/<name>.md` — one page per
  person/group the user cares about, with an `INDEX.md` in each dir.

A **consolidation pass** runs on a schedule (e.g. hourly when there is
new signal): it reads recent notes and conversation, extracts durable
facts, and updates `MEMORY.md` and the people/group pages. Raw notes are
never edited — consolidation only promotes upward. See `memory/`.

Why files: human-readable, trivially backed up, diffable, and the agent
already has file tools — no new infrastructure.

## 6. Skills: SKILL.md playbooks

A skill is a **reusable workflow written as Markdown**: a `SKILL.md`
with YAML frontmatter (`name`, `description`) plus instructions,
examples, and scripts. Examples: reading Gmail, booking travel,
searching products.

- **Discovery:** at task start, the agent keyword-searches skill
  descriptions against the request and loads only the best match into
  context. Skills stay out of the prompt until needed.
- **Authoring:** when a recurring workflow proves useful, the agent
  writes it up as a new skill; ineffective skills are retired.
- Relative paths inside a skill resolve against the skill's own
  directory, so skills are portable.

See `skills/` for the spec and a loader sketch.

## 7. Tool integrations behind one interface

Shell, files, browser, HTTP APIs, device commands — all exposed through
**one registry**: `name → {description, json_schema, handler}`. The model
sees uniform function definitions; the runtime maps each call to its
handler. Adding a capability = adding one registry entry, never
changing the loop.

Rules for tool authors:
- Tools are dumb and narrow; judgment stays in the model + approvals.
- Every tool validates its inputs and returns structured results or
  clear errors — never raw tracebacks to the model if avoidable.
- Tools that touch the outside world declare it in their description.

See `agent/tools/`.

## 8. Approval gates

Actions are classified **reversible** vs **consequential**:

- *Reversible* (read a file, run a local command, search the web):
  run freely.
- *Consequential* (send a message/email, make a purchase or booking,
  use a credential, join a network, delete data, change persistent
  state like scheduled jobs): **pause and ask the user**, showing
  exactly what will happen. Proceed only on explicit confirmation.

The gate sits between the model's tool call and the tool's execution —
the model cannot bypass it. Timeouts default to abort. Standing
permissions (e.g. "this scheduled job may send its own emails") are
explicit, narrow, and revocable. See `agent/approvals.py`.

## 9. Proactivity

Background jobs don't just maintain state — they **surface items worth
interrupting the user for**: a reminder whose condition is now true, a
goal that needs attention, something learned that changes a plan.

Principles:
- One item per interruption, and it must be worth the cost.
- Ordinary items wait for waking hours and a quiet moment; urgent
  ones go immediately.
- A promised reminder is a scheduled job the agent owns; the
  proactivity layer never "promises" to carry a specific item.
- The user steers volume with plain-language feedback ("fewer of
  these"), recorded as a preference.

Proactivity is the difference between an assistant that answers and an
agent that acts: the scheduler and memory passes exist so the loop has
something useful to say when the user *hasn't* asked anything.
