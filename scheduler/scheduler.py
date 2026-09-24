"""Cron scheduler: real 5-field cron parsing + next-run computation.

Jobs persist in a JSON file so they survive restarts. A poller finds
due jobs and hands each one's task to the agent loop as a fresh turn.

Job schema:
  {"id": "...", "cron": "0 9 * * MON-FRI", "task": "prompt for the agent",
   "last_run": "2026-09-24T09:00:00-04:00", "enabled": true}

Cron dialect (standard 5-field, Vixie-like):
  minute hour day-of-month month day-of-week
    minute:       0-59
    hour:         0-23
    day-of-month: 1-31
    month:        1-12 (JAN-DEC accepted)
    day-of-week:  0-6, Sunday is 0 or 7 (MON-SUN accepted)

  Each field supports: "*" (all), "*/n" (every n), "a-b" (range),
  "a-b/n" (stepped range), "a,b,c" (lists), and mixes like "1,15-30/5".
  day-of-month and day-of-week follow the standard OR rule: when both
  are restricted, a day matches if EITHER matches; when one is "*",
  the other one alone controls.

Timezone / DST assumptions:
  - Pass timezone-aware datetimes. Everything is computed in the tzinfo
    attached to ``after``.
  - Recommended: run the scheduler on UTC and write expressions in UTC.
    On DST transitions a wall-clock schedule shifts by an hour twice a
    year; with UTC cron there is no ambiguity.
  - If you do pass a zoneinfo local time, a nonexistent wall-clock time
    (spring-forward gap) simply never matches, and an ambiguous time
    (fall-back fold) may match twice — standard naive-datetime behavior.
    The scaffold does not special-case folds.

Run self-test:  python -m scheduler.scheduler
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

JOBS_FILE = os.path.expanduser("~/agent-workspace/scheduler/jobs.json")

_MONTH_NAMES = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_DOW_NAMES = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4,
              "FRI": 5, "SAT": 6}  # cron numbering; normalized to Python after parse

# (min, max) per field, in cron numbering.
_FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "month": (1, 12),
    "day_of_week": (0, 7),  # 7 == Sunday, normalized to 0
}
_FIELD_ORDER = ("minute", "hour", "day_of_month", "month", "day_of_week")


def _atom_value(token: str, names: dict | None, lo: int, hi: int) -> int:
    token = token.strip().upper()
    if names and token in names:
        return names[token]
    value = int(token)  # raises ValueError on garbage — good
    if not lo <= value <= hi:
        raise ValueError(f"value {value} out of range {lo}-{hi}")
    return value


def _parse_field(field: str, lo: int, hi: int,
                 names: dict | None = None) -> set[int]:
    """Parse one cron field into a set of ints (cron numbering)."""
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty element in cron field {field!r}")
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError(f"step must be >= 1 in {part}/{step_s}")
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            start_s, end_s = part.split("-", 1)
            start = _atom_value(start_s, names, lo, hi)
            end = _atom_value(end_s, names, lo, hi)
            if start > end:
                raise ValueError(f"reversed range {part!r}")
        else:
            # "5/10" style: from 5 up to max, stepping 10.
            start = end = _atom_value(part, names, lo, hi)
            if "/" in field and "-" not in part and part != "*":
                pass  # start==end already; extend end below
            if step != 1 and start == end and "/" in field:
                # single value with a step: range from value to max
                end = hi
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError(f"field {field!r} matched nothing")
    return values


def parse_cron(expr: str) -> dict[str, set[int]]:
    """Parse a 5-field cron expression into sets of ints.

    Returned dict keys: minute, hour, day_of_month, month, day_of_week
    (day_of_week in Python weekday numbering: Monday=0 .. Sunday=6).

    >>> sorted(parse_cron("*/15 9 * * MON-FRI")["minute"])
    [0, 15, 30, 45]
    >>> sorted(parse_cron("0 0 1 JAN,MAR *")["month"])
    [1, 3]
    >>> sorted(parse_cron("0 12 * * 0")["day_of_week"])
    [6]
    >>> sorted(parse_cron("0 12 * * 7")["day_of_week"])
    [6]
    """
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron expression needs 5 fields, got {len(parts)}: {expr!r}")
    out = {}
    for name, part in zip(_FIELD_ORDER, parts):
        lo, hi = _FIELD_RANGES[name]
        names = _MONTH_NAMES if name == "month" else _DOW_NAMES if name == "day_of_week" else None
        out[name] = _parse_field(part, lo, hi, names)
    # Normalize cron dow (0=Sunday..6=Saturday, 7=Sunday) to Python
    # weekday (Monday=0..Sunday=6).
    out["day_of_week"] = {(d % 7 + 6) % 7 for d in out["day_of_week"]}
    return out


def _matches(spec: dict[str, set[int]], dt: datetime,
             dom_star: bool, dow_star: bool) -> bool:
    if dt.minute not in spec["minute"]:
        return False
    if dt.hour not in spec["hour"]:
        return False
    if dt.month not in spec["month"]:
        return False
    dom_ok = dt.day in spec["day_of_month"]
    dow_ok = dt.weekday() in spec["day_of_week"]
    if dom_star and dow_star:
        day_ok = True
    elif dom_star:
        day_ok = dow_ok
    elif dow_star:
        day_ok = dom_ok
    else:
        day_ok = dom_ok or dow_ok  # standard cron OR rule
    return day_ok


def next_run(expr: str, after: datetime) -> datetime:
    """First datetime strictly after ``after`` matching the cron expression.

    Keeps the tzinfo of ``after``. Scans forward minute by minute, capped
    at 366 days (a cron schedule always repeats within a year).

    >>> from datetime import datetime
    >>> next_run("0 9 * * *", datetime(2026, 9, 24, 8, 0))
    datetime.datetime(2026, 9, 24, 9, 0)
    >>> next_run("*/15 * * * *", datetime(2026, 9, 24, 10, 7))
    datetime.datetime(2026, 9, 24, 10, 15)
    >>> next_run("30 9 * * MON-FRI", datetime(2026, 9, 25, 10, 0))  # a Friday
    datetime.datetime(2026, 9, 28, 9, 30)
    >>> next_run("0 0 1 * *", datetime(2026, 9, 24, 12, 0))
    datetime.datetime(2026, 10, 1, 0, 0)
    >>> # dom/dow OR: fires on the 1st of the month OR on Mondays
    >>> next_run("0 9 1 * MON", datetime(2026, 9, 24, 12, 0))  # Thu Sep 24
    datetime.datetime(2026, 9, 28, 9, 0)
    """
    spec = parse_cron(expr)
    dom_star = spec["day_of_month"] == set(range(1, 32))
    dow_star = spec["day_of_week"] == set(range(7))
    candidate = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    limit = candidate + timedelta(days=366)
    while candidate <= limit:
        if _matches(spec, candidate, dom_star, dow_star):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError(f"no run of {expr!r} within 366 days of {after!r}")


# ---- Job persistence & polling ----------------------------------------

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


def due_jobs(jobs: list[dict], now: datetime | None = None) -> list[dict]:
    """Jobs whose next scheduled run is at or before ``now``.

    A job with no ``last_run`` is due immediately (first run), then its
    schedule takes over.
    """
    now = now or datetime.now(timezone.utc)
    due = []
    for job in jobs:
        if not job.get("enabled", True):
            continue
        last_run = job.get("last_run")
        if not last_run:
            due.append(job)
            continue
        last = datetime.fromisoformat(last_run)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if next_run(job["cron"], last) <= now:
            due.append(job)
    return due


def mark_run(job: dict, now: datetime | None = None) -> None:
    job["last_run"] = (now or datetime.now(timezone.utc)).isoformat()


def run_pending(jobs: list[dict], runner, now: datetime | None = None,
                jobs_path: str = JOBS_FILE) -> list[str]:
    """Run every due job via ``runner(job)`` and persist ``last_run``.

    ``runner`` is a callable taking the job dict (the host wires this to
    agent.loop.run_loop). Returns the ids that ran. Jobs should be
    idempotent: assume a run can happen twice (crash between run and
    mark_run) and design tasks accordingly.
    """
    now = now or datetime.now(timezone.utc)
    ran = []
    for job in due_jobs(jobs, now):
        runner(job)
        mark_run(job, now)
        ran.append(job.get("id"))
    if ran:
        save_jobs(jobs, jobs_path)
    return ran


def self_test() -> None:
    import doctest
    results = doctest.testmod(verbose=False)
    assert results.failed == 0, f"{results.failed} doctests failed"
    # due_jobs wiring
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    jobs = [
        {"id": "hourly", "cron": "0 * * * *", "task": "t",
         "last_run": "2026-09-24T11:00:00+00:00", "enabled": True},
        {"id": "daily", "cron": "0 9 * * *", "task": "t",
         "last_run": "2026-09-24T09:00:00+00:00", "enabled": True},
        {"id": "disabled", "cron": "* * * * *", "task": "t", "enabled": False},
        {"id": "never", "cron": "0 9 * * *", "task": "t"},  # no last_run -> due
    ]
    due = {j["id"] for j in due_jobs(jobs, now)}
    assert due == {"hourly", "never"}, f"unexpected due set: {due}"
    # invalid expressions raise
    for bad in ["* * * *", "60 * * * *", "0 0 * * FUNDAY", "*/0 * * * *"]:
        try:
            parse_cron(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} should have raised ValueError")
    print(f"cron self-test OK ({results.attempted} doctests)")


if __name__ == "__main__":
    self_test()
