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
| `agent/approvals.py` | Reversible vs consequential action gates |
| `memory/` | MEMORY.md template, daily notes, people/groups pages |
| `skills/` | SKILL.md spec, one example skill, loader sketch |
| `scheduler/` | Cron-like scheduler sketch + event-hook concept |
| `config.yaml.example` | Model endpoint, paths, timezone, approval policy |
