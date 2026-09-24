# personal-agent-harness

A starter scaffold for a **persistent personal AI agent**: one tool-calling
language model, a runtime loop, and per-user compute that survives between
conversations — plus file-backed memory, skills, a scheduler, and approval
gates.

## Honest note

This is a **clean-room reconstruction from observable patterns**, not a copy
of any production system. It is meant to teach the architecture and give
you a starting point, not to be a finished framework. The core subsystems
— cron parsing, the approval UI, BM25 skill search, and the nightly
dreaming pass — are real, tested implementations. Remaining rough edges
(sandboxing, path jailing, Copilot token caching, …) are marked with
honest TODOs in the code.

## The idea in one paragraph

A provider-agnostic chat model sits at the center (`agent/loop.py`). It
reasons, calls tools (`agent/tools/`), and observes results in a loop. It
runs on persistent per-user compute (a VM or container that doesn't die when
the chat closes). Memory is plain Markdown on disk (`memory/`), updated by a
background consolidation pass. Reusable workflows are `SKILL.md` playbooks
(`skills/`). Recurring work runs on a cron-like scheduler (`scheduler/`).
Anything consequential — sending messages, spending money, touching
credentials, joining networks — pauses for explicit user approval
(`agent/approvals.py`).

## Quickstart

Two ways to give the agent a model. Pick one.

### Path A — bring your own API key

```bash
# 1. Copy and edit the config
cp config.yaml.example config.yaml
#    provider.kind: openai_compatible   (or: anthropic)

# 2. Install deps
pip install -r requirements.txt

# 3. Put your key in the environment (never in the config file)
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY=...

# 4. Run (consequential actions pause for your approval)
python -m agent.loop "Remind me to stretch every hour"
```

`provider.base_url` points at any OpenAI-compatible chat completions
endpoint — OpenAI, OpenRouter, a local Ollama/vLLM server, a LiteLLM
proxy. Swapping providers is a config change, not a code change.

### Path B — GitHub Copilot as the provider

> **Unofficial and best-effort.** This uses Copilot's internal chat
> endpoint (`https://api.githubcopilot.com/chat/completions`), which is
> not a public API and can break at any time. It requires **your own
> paid GitHub Copilot subscription** — review GitHub's terms before
> using it. Full warnings in `agent/providers.py`.

```bash
# 1. Copy and edit the config
cp config.yaml.example config.yaml
#    provider.kind:  github_copilot
#    provider.model: gpt-4o            (or another Copilot-served model)
#    provider.api_key: "${COPILOT_TOKEN}"

# 2. Install deps
pip install -r requirements.txt

# 3. Mint a short-lived Copilot token from a GitHub token on your account
export GITHUB_TOKEN=...   # classic PAT/OAuth token tied to your Copilot plan
export COPILOT_TOKEN=$(python -c "
from agent.providers import get_copilot_token
import os; print(get_copilot_token(os.environ['GITHUB_TOKEN']))")

# 4. Run
python -m agent.loop "Remind me to stretch every hour"
```

The Copilot token expires quickly — re-mint it when calls start failing
with auth errors. (TODO in the scaffold: cache it until near expiry
instead of re-exchanging every run.)

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design doc.

## Layout

| Path | What it is |
|---|---|
| `agent/loop.py` | Reason → act → observe loop, builds model client via `agent/providers.py` |
| `agent/providers.py` | Provider abstraction: OpenAI-compatible, Anthropic, GitHub Copilot (unofficial) |
| `agent/config.py` | Config loader with `${ENV_VAR}` interpolation |
| `agent/tools/` | Example tools (shell exec, file read/write) + registry |
| `agent/approvals.py` | Approval gates: card UI, approve/deny/edit, timeout, JSONL audit log |
| `agent/dream.py` | Nightly dreaming pass: reflection report + safe MEMORY.md updates |
| `memory/` | MEMORY.md, daily notes, people/groups pages, `dreams/` reports |
| `skills/` | SKILL.md spec, one example skill, BM25 loader + search |
| `scheduler/` | Real 5-field cron parser (`next_run`) + persistent job poller |
| `config.yaml.example` | Model endpoint, paths, timezone, approval policy |

## Recurring work

Two kinds: **cron jobs** (poll-based, at-least-once) and the **dreaming pass**.

Add a cron job to `~/agent-workspace/scheduler/jobs.json`:

```json
[
  {"id": "morning-brief", "cron": "0 7 * * MON-FRI",
   "task": "Write my morning briefing.", "enabled": true}
]
```

Then poll for due jobs (wire `run_pending` to `agent.loop.run_loop`):

```python
from scheduler.scheduler import load_jobs, run_pending
from agent.loop import run_loop, load_app_config

cfg = load_app_config()
run_pending(load_jobs(), lambda job: run_loop(job["task"], cfg))
```

The cron parser (`scheduler/scheduler.py`) supports standard 5-field
expressions: ranges, steps, lists, and `MON`/`JAN`-style names, e.g.
`*/15 9-17 * * MON-FRI`. `next_run(expr, after)` computes the next fire
time; run the scheduler on UTC and write expressions in UTC to avoid
DST ambiguity.

The **nightly dreaming pass** (`agent/dream.py`) reflects over the day's
memory and writes a dated report to `memory/dreams/`, applying only
append-style, deduplicated updates to MEMORY.md. Run it manually:

```bash
python -m agent.dream --dry-run   # inspect the plan, change nothing
python -m agent.dream             # run tonight's pass
```

Or schedule it with cron (3 AM daily):

```bash
0 3 * * * cd ~/personal-agent-harness && python -m agent.dream >> dream-cron.log 2>&1
```

Headless runs can set `HARNESS_AUTO_APPROVE=deny` (deny everything) or
`HARNESS_AUTO_APPROVE=approve-reversible` (auto-approve reversible
actions only, deny consequential ones) so the approval gate fails closed
instead of blocking on a prompt.
