"""Cron-like scheduler sketch.

Jobs persist in a JSON file so they survive restarts. A poller finds
due jobs and hands each one's task to the agent loop as a fresh turn.

Job schema:
  {"id": "...", "schedule": "0 9 * * *", "task": "prompt for the agent",
   "last_run": "2026-09-24T09:00:00-04:00", "enabled": true}
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

JOBS_FILE = os.path.expanduser("~/agent-workspace/scheduler/jobs.json")


def load_jobs(path: str = JOBS_FILE) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_jobs(jobs: list[dict], path: str = JOBS_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)
    os.replace(tmp, path)  # atomic write: never a half-written job list


def _cron_due(schedule: str, now: datetime) -> bool:
    # TODO: real cron parsing (croniter). This stub supports only
    # "every N minutes" written as "*/N * * * *".
    parts = schedule.split()
    if len(parts) == 5 and parts[0].startswith("*/") and parts[1:] == ["*", "*", "*", "*"]:
        return now.minute % int(parts[0][2:]) == 0
    raise NotImplementedError(f"unsupported schedule in stub: {schedule}")


def due_jobs(jobs: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    return [j for j in jobs
            if j.get("enabled", True) and _cron_due(j["schedule"], now)]


def mark_run(job: dict, now: datetime | None = None) -> None:
    job["last_run"] = (now or datetime.now(timezone.utc)).isoformat()


# TODO: poller loop — every poll_interval_seconds: for job in due_jobs():
#   run agent.loop.run_loop(job["task"], cfg); mark_run(job); save_jobs(jobs).
# Jobs must be idempotent: assume a run can happen twice (crash between
# run and mark_run) and design tasks accordingly.
