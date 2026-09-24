"""Shell execution tool: run a command with a timeout.

Kept deliberately narrow: no interactive input, no backgrounding here
(background jobs belong to the scheduler, not ad-hoc tool calls).
"""

from __future__ import annotations

import subprocess

# TODO: sandbox this (restricted PATH, blocked commands, resource limits).
BLOCKED_PREFIXES = ("rm -rf /", "mkfs", ":(){")  # minimal guardrail, not a sandbox


def exec(command: str, timeout_seconds: int = 30) -> dict:
    if command.strip().startswith(BLOCKED_PREFIXES):
        return {"ok": False, "error": "blocked command pattern"}
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {timeout_seconds}s"}
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4000:],  # TODO: proper paging for long output
        "stderr": proc.stderr[-2000:],
    }
