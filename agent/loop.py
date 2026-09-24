"""Minimal provider-agnostic tool-calling agent loop.

Talks to any OpenAI-compatible chat completions endpoint:
POST {base_url}/chat/completions with {model, messages, tools}.

Run:  python -m agent.loop "your task here"
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

from . import approvals
from .tools import registry as tools


def chat_completions(base_url: str, api_key: str, model: str,
                     messages: list, tool_defs: list) -> dict:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "tools": tool_defs,
        # TODO: tune per provider (temperature, max_tokens, tool_choice).
    }).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def run_loop(user_task: str, cfg: dict, ask_user=approvals.console_ask) -> str:
    base_url = cfg["model"]["base_url"]
    api_key = os.environ[cfg["model"]["api_key_env"]]  # never hardcode keys
    model = cfg["model"]["name"]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_task},
    ]
    tool_defs = tools.definitions()

    for _ in range(25):  # safety cap on loop iterations
        response = chat_completions(base_url, api_key, model, messages, tool_defs)
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

# TODO: load config.yaml (yaml.safe_load) instead of this stub.
DEFAULT_CFG = {
    "model": {"base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
              "name": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
              "api_key_env": "OPENAI_API_KEY"},
    "approvals": {"policy": "confirm_consequential", "timeout_seconds": 300},
}


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Say hello and list the workspace directory."
    print(run_loop(task, DEFAULT_CFG))
