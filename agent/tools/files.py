"""File read/write tool. Directories list; text files page."""

from __future__ import annotations

import os

# TODO: jail paths to the workspace root so tools can't wander the FS.
WORKSPACE = os.path.expanduser("~/agent-workspace")


def _resolve(path: str) -> str:
    p = os.path.abspath(os.path.expanduser(path))
    # TODO: enforce p.startswith(WORKSPACE)
    return p


def read(path: str, limit: int | None = None) -> dict:
    p = _resolve(path)
    if os.path.isdir(p):
        return {"ok": True, "type": "directory",
                "entries": sorted(os.listdir(p))[:200]}
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {"ok": False, "error": "not found"}
    except UnicodeDecodeError:
        return {"ok": False, "error": "not a text file"}
    if limit:
        lines = lines[:limit]
    return {"ok": True, "type": "file", "content": "".join(lines)}


def write(path: str, content: str, mode: str = "overwrite") -> dict:
    p = _resolve(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "a" if mode == "append" else "w", encoding="utf-8") as f:
        f.write(content)
    return {"ok": True, "path": p, "bytes": len(content.encode())}
