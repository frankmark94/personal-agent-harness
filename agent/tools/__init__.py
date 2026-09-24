"""One registry for every tool: name -> {description, schema, handler}.

The model sees uniform function definitions; the loop never changes
when a new tool is added — just register it here.
"""

from __future__ import annotations

from . import shell, files

_REGISTRY: dict[str, dict] = {}


def register(name: str, description: str, parameters: dict, handler):
    _REGISTRY[name] = {
        "description": description,
        "parameters": parameters,
        "handler": handler,
    }


def definitions() -> list:
    """OpenAI-style tool definitions for the chat API."""
    return [{
        "type": "function",
        "function": {
            "name": name,
            "description": t["description"],
            "parameters": t["parameters"],
        },
    } for name, t in _REGISTRY.items()]


def run(name: str, args: dict):
    if name not in _REGISTRY:
        return {"ok": False, "error": f"unknown tool: {name}"}
    return _REGISTRY[name]["handler"](**args)


# Built-in tools. TODO: add browser, http, device tools the same way.
register(
    "shell_exec",
    "Run a shell command with a timeout. Returns stdout/stderr/exit code.",
    {"type": "object",
     "properties": {"command": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "default": 30}},
     "required": ["command"]},
    shell.exec,
)

register(
    "file_read",
    "Read a text file (or list a directory).",
    {"type": "object",
     "properties": {"path": {"type": "string"},
                    "limit": {"type": "integer"}},
     "required": ["path"]},
    files.read,
)

register(
    "file_write",
    "Write content to a file (creates parents). Overwrites by default.",
    {"type": "object",
     "properties": {"path": {"type": "string"},
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["overwrite", "append"],
                             "default": "overwrite"}},
     "required": ["path", "content"]},
    files.write,
)
