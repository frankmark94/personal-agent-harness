# Event hooks

"When X happens, do Y" — the event-driven counterpart to cron jobs.

## Concept

A hook has a **trigger** instead of a schedule:

| Trigger | Example |
|---|---|
| File watcher | `memory/` changed → run consolidation early |
| Webhook receiver | new email arrives → triage it |
| Poller | inbox has unread VIP mail → surface it |

When the trigger fires, the hook's task (a prompt, like a cron job's)
is injected into the agent loop as a fresh turn.

## Why separate from cron

- **Failure modes differ.** A missed cron run needs catch-up logic;
  a missed event needs redelivery or a reconciliation sweep.
- **Delivery guarantees differ.** Cron is at-least-once by polling;
  events need dedup (idempotency keys) so a retried webhook doesn't
  double-act.

## Rules

- Hook tasks must be idempotent, same as cron jobs.
- Each hook declares what it may do (tool allowlist); a file-watcher
  hook shouldn't be able to send email.
- Log every firing: trigger, time, action taken. Silent hooks are
  untrustworthy hooks.

## Sketch

```python
# TODO: real implementation
HOOKS = [
    {"trigger": {"type": "webhook", "path": "/hooks/email"},
     "task": "Triage the newly arrived email.",
     "allow_tools": ["file_read", "file_write"]},
]

def on_event(hook, event):
    if event.key in seen_keys:   # dedup
        return
    run_loop(hook["task"] + f"\nEvent: {event.summary}", cfg,
             allowed_tools=hook["allow_tools"])
```
