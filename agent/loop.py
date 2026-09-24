"""Minimal provider-agnostic tool-calling agent loop.

The model client is built by agent/providers.py from the ``provider:``
section of config.yaml — plain API keys (OpenAI-compatible or Anthropic)
or GitHub Copilot as the provider. The loop only ever calls
``provider.chat(messages, tools)`` and never touches HTTP itself.

Run:  python -m agent.loop "your task here"
"""

from __future__ import annotations

import json
import os
import sys

from . import approvals
from . import config as config_mod
from . import providers
from .tools import registry as tools


def run_loop(user_task: str, cfg: dict, ask_user=approvals.console_ask) -> str:
    provider = providers.from_config(cfg["provider"])

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_task},
    ]
    tool_defs = tools.definitions()

    for _ in range(25):  # safety cap on loop iterations
        response = provider.chat(messages, tool_defs)
        msg = response["choices"][0]["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return msg.get("content", "")  # final answer

        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"].get("arguments") or "{}")
            try:
                approvals.check(name, args, policy=cfg["approvals"], ask_user=ask_user)
                result = tools.run(name, args)
            except approvals.Denied as e:
                result = {"ok": False, "error": f"denied by approval gate: {e}"}
            except Exception as e:  # TODO: narrower handling per tool
                result = {"ok": False, "error": str(e)}
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result),
            })

    return "[stopped: iteration cap reached]"


SYSTEM_PROMPT = """\
You are a personal AI agent running on the user's own persistent computer.
You have tools; use them instead of guessing. Prefer reversible actions.
For consequential actions (sending messages, purchases, credentials,
deleting data, network joins), the runtime will ask the user — just
call the tool and report the outcome.
Be concise. State facts from tool output, not from memory.
"""

DEFAULT_CFG = {
    "provider": {
        "kind": os.environ.get("AGENT_PROVIDER", "openai_compatible"),
        "model": os.environ.get("AGENT_MODEL", "gpt-4o-mini"),
        "base_url": os.environ.get("AGENT_BASE_URL", "https://api.openai.com/v1"),
        "api_key": os.environ.get("AGENT_API_KEY", ""),
    },
    "approvals": {"policy": "confirm_consequential", "timeout_seconds": 300},
}


def load_app_config() -> dict:
    try:
        return config_mod.load_config("config.yaml")
    except FileNotFoundError:
        # TODO: log a one-line notice that defaults are in effect.
        return DEFAULT_CFG


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Say hello and list the workspace directory."
    print(run_loop(task, load_app_config()))
