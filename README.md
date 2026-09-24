# personal-agent-harness

A starter scaffold for a **persistent personal AI agent**: one tool-calling
language model, a runtime loop, and per-user compute that survives between
conversations — plus file-backed memory, skills, a scheduler, and approval
gates.

## Honest note

This is a **clean-room reconstruction from observable patterns**, not a copy
of any production system. Every file is a skeleton with TODO markers where a
real implementation would go. It is meant to teach the architecture and give
you a starting point, not to be a finished framework.

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

```bash
# 1. Copy and edit the config
cp config.yaml.example config.yaml

# 2. Install deps
pip install -r requirements.txt

# 3. Set your model key (any OpenAI-compatible endpoint)
export OPENAI_API_KEY=...

# 4. Run the loop (it will refuse consequential actions until you approve)
python -m agent.loop "Remind me to stretch every hour"
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design doc.

## Layout

| Path | What it is |
|---|---|
| `agent/loop.py` | Reason → act → observe loop, provider-agnostic |
| `agent/tools/` | Example tools (shell exec, file read/write) + registry |
| `agent/approvals.py` | Reversible vs consequential action gates |
| `memory/` | MEMORY.md template, daily notes, people/groups pages |
| `skills/` | SKILL.md spec, one example skill, loader sketch |
| `scheduler/` | Cron-like scheduler sketch + event-hook concept |
| `config.yaml.example` | Model endpoint, paths, timezone, approval policy |
