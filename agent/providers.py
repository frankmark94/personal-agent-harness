"""Model provider abstraction: how the agent loop talks to an LLM.

Two auth paths, per the user's choice:

  1. Plain API keys — an OpenAI-compatible chat completions endpoint, or
     Anthropic's messages API.
  2. GitHub Copilot as the provider — an UNOFFICIAL endpoint (see the
     warnings on GitHubCopilotProvider). Use at your own risk.

Contract: the loop only ever calls ``provider.chat(messages, tools)`` and
gets back an OpenAI-shaped chat completion dict — i.e.
``response["choices"][0]["message"]`` with an optional ``"tool_calls"``
list. Provider-specific wire formats are converted here so the loop
itself stays provider-agnostic.
"""

from __future__ import annotations

import json

import requests


class Provider:
    """Base class. Subclasses implement chat() and return OpenAI-shaped dicts."""

    name = "base"

    def chat(self, messages: list, tools: list) -> dict:
        raise NotImplementedError


class OpenAICompatibleProvider(Provider):
    """Any endpoint that speaks POST {base_url}/chat/completions.

    Covers OpenAI, OpenRouter, Ollama, vLLM, LiteLLM proxies, etc.
    """

    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, model: str,
                 extra_headers: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra_headers = extra_headers or {}

    def chat(self, messages: list, tools: list) -> dict:
        body = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
        # TODO: tune per provider (temperature, max_tokens, tool_choice).
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        headers.update(self.extra_headers)
        resp = requests.post(f"{self.base_url}/chat/completions",
                             json=body, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()


class AnthropicProvider(Provider):
    """Anthropic's messages API, converted to the OpenAI shape the loop expects.

    Skeleton-grade conversion: covers text + tool_use/tool_result round
    trips. Streaming, thinking blocks, prompt caching, and multi-part
    content are out of scope for the scaffold.
    """

    name = "anthropic"
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    # ---- OpenAI shape -> Anthropic shape ----

    @staticmethod
    def _to_anthropic_tools(openai_tools: list) -> list:
        converted = []
        for t in openai_tools or []:
            fn = t.get("function", t)  # tolerate already-flat defs
            converted.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                # TODO: validate this is a JSON Schema object.
                "input_schema": fn.get("parameters", {"type": "object"}),
            })
        return converted

    @staticmethod
    def _to_anthropic_messages(messages: list) -> tuple[str | None, list]:
        system_parts, converted = [], []
        for m in messages:
            role, content = m.get("role"), m.get("content")
            if role == "system":
                system_parts.append(content if isinstance(content, str) else "")
                continue
            if role == "assistant" and m.get("tool_calls"):
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for call in m["tool_calls"]:
                    blocks.append({
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        # TODO: handle non-JSON arguments gracefully.
                        "input": json.loads(call["function"].get("arguments") or "{}"),
                    })
                converted.append({"role": "assistant", "content": blocks})
                continue
            if role == "tool":
                # TODO: group consecutive tool results into one user message.
                converted.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": content if isinstance(content, str)
                               else json.dumps(content),
                }]})
                continue
            converted.append({"role": role, "content": content})
        system = "\n\n".join(p for p in system_parts if p) or None
        return system, converted

    # ---- Anthropic shape -> OpenAI shape ----

    @staticmethod
    def _from_anthropic_response(data: dict) -> dict:
        text_parts, tool_calls = [], []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })
        message = {"role": "assistant", "content": "".join(text_parts) or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        # TODO: map stop_reason -> finish_reason faithfully.
        return {"choices": [{"message": message,
                             "finish_reason": data.get("stop_reason")}]}

    def chat(self, messages: list, tools: list) -> dict:
        system, anthropic_messages = self._to_anthropic_messages(messages)
        body = {
            "model": self.model,
            # TODO: make max_tokens configurable; Anthropic requires it.
            "max_tokens": 4096,
            "messages": anthropic_messages,
        }
        if system:
            body["system"] = system
        anthropic_tools = self._to_anthropic_tools(tools)
        if anthropic_tools:
            body["tools"] = anthropic_tools
        resp = requests.post(
            self.API_URL,
            json=body,
            headers={"x-api-key": self.api_key,
                     "anthropic-version": self.API_VERSION,
                     "Content-Type": "application/json"},
            timeout=120,
        )
        resp.raise_for_status()
        return self._from_anthropic_response(resp.json())


class GitHubCopilotProvider(OpenAICompatibleProvider):
    """GitHub Copilot as the model provider.

    ------------------------------------------------------------------
    UNOFFICIAL ENDPOINT — READ THIS BEFORE USING
    ------------------------------------------------------------------
    * ``https://api.githubcopilot.com/chat/completions`` is NOT a public,
      documented GitHub API. It is the internal endpoint used by Copilot
      editor plugins, and the community pattern below reverse-engineers
      how those plugins authenticate.
    * It works with a short-lived token derived from YOUR OWN paid
      GitHub Copilot subscription (see get_copilot_token). Do not use
      someone else's token.
    * It may break, change shape, or be shut off at any time without
      notice. Treat every Copilot-provider feature as best-effort.
    * Review GitHub's Terms of Service and the Copilot subscription
      terms before using this; automated/agent use may fall outside
      what your plan permits.
    ------------------------------------------------------------------

    Wire format is OpenAI-compatible chat completions, so this subclasses
    OpenAICompatibleProvider with the base URL fixed.
    """

    name = "github_copilot"
    BASE_URL = "https://api.githubcopilot.com/chat/completions"

    def __init__(self, copilot_token: str, model: str):
        # TODO: some community clients also send Editor-Version /
        # User-Agent headers; add if the endpoint starts rejecting calls.
        super().__init__(self.BASE_URL, copilot_token, model)


def get_copilot_token(github_token: str) -> str:
    """Exchange a GitHub token for a short-lived Copilot token.

    Community pattern (BEST-EFFORT, subject to change without notice):
    a GitHub OAuth token / classic PAT with Copilot-related scopes is
    POSTed to GitHub's internal Copilot token endpoint, which returns JSON
    containing a short-lived ``token`` shaped like
    ``tid=...;exp=...;sku=...``. That token is what GitHubCopilotProvider
    expects as ``copilot_token``.

    The exact endpoint, required scopes, and response shape have changed
    before and will change again — check current community clients
    (e.g. open-source Copilot plugin reimplementations) if this breaks.
    TODO: cache the token until near its ``exp`` instead of exchanging
    on every run.
    """
    resp = requests.post(
        "https://api.github.com/copilot_internal/v2/token",
        headers={
            "Authorization": f"token {github_token}",
            "Accept": "application/json",
            # TODO: confirm the currently-working headers/body; some
            # clients use GET here, some send an empty JSON body.
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # TODO: handle error payloads (e.g. no Copilot subscription) with a
    # clear message instead of KeyError.
    return data["token"]


def from_config(provider_cfg: dict) -> Provider:
    """Build a Provider from the ``provider:`` section of the config.

    Expected keys: kind (openai_compatible | anthropic | github_copilot),
    model, base_url (openai_compatible only), api_key (already
    ${ENV_VAR}-interpolated by the config loader).
    """
    kind = provider_cfg.get("kind", "openai_compatible")
    model = provider_cfg["model"]
    api_key = provider_cfg.get("api_key", "")

    if kind == "openai_compatible":
        return OpenAICompatibleProvider(provider_cfg["base_url"], api_key, model)
    if kind == "anthropic":
        return AnthropicProvider(api_key, model)
    if kind == "github_copilot":
        return GitHubCopilotProvider(api_key, model)
    raise ValueError(
        f"unknown provider kind: {kind!r} "
        "(expected openai_compatible | anthropic | github_copilot)"
    )
