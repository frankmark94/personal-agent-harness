"""Nightly dreaming pass: reflection over the day's memory.

Reads ``memory/daily-notes.md``, ``memory/MEMORY.md``, and recent dream
reports, then asks the configured model to reflect: candidate memory
updates, alignment observations, and open questions. The full reflection
is saved as a dated report in ``memory/dreams/YYYY-MM-DD.md``.

Only safe, clearly-scoped updates are applied to MEMORY.md: one-line
facts the model marks with ``@@UPDATE@@ `` are appended to a dedicated
"dream updates" section (deduplicated). Everything else lives only in
the dated report. Nothing is ever destructively rewritten.

Usage:
    python -m agent.dream              # run tonight's pass
    python -m agent.dream --dry-run    # print the plan + prompt, change nothing

Schedule it (cron example, 3 AM daily):
    0 3 * * * cd ~/personal-agent-harness && python -m agent.dream >> dream-cron.log 2>&1
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys

from . import config as config_mod
from . import providers

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR = os.path.join(REPO_ROOT, "memory")
DREAMS_DIR = os.path.join(MEMORY_DIR, "dreams")
UPDATE_MARKER = "@@UPDATE@@ "
DREAM_SECTION = "## Dream updates (auto-appended)"

# Prompt budget caps (chars) so a growing memory file can't blow the context.
_CAPS = {"MEMORY.md": 8000, "daily-notes.md": 6000, "dream": 4000}


def _read_capped(path: str, cap: int) -> str:
    if not os.path.isfile(path):
        return f"(missing: {os.path.basename(path)})"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if len(text) > cap:
        return text[:cap] + f"\n…(truncated, {len(text) - cap} chars omitted)"
    return text


def _recent_dreams(limit: int = 3) -> list[str]:
    if not os.path.isdir(DREAMS_DIR):
        return []
    files = sorted(f for f in os.listdir(DREAMS_DIR) if f.endswith(".md"))
    return files[-limit:]


def build_prompt() -> str:
    memory_md = _read_capped(os.path.join(MEMORY_DIR, "MEMORY.md"),
                            _CAPS["MEMORY.md"])
    daily = _read_capped(os.path.join(MEMORY_DIR, "daily-notes.md"),
                         _CAPS["daily-notes.md"])
    dreams = _recent_dreams()
    dream_texts = "\n\n".join(
        f"### {name}\n{_read_capped(os.path.join(DREAMS_DIR, name), _CAPS['dream'])}"
        for name in dreams) or "(no previous dream reports)"

    return f"""\
You are doing the nightly reflection ("dreaming") pass for a persistent
personal AI agent. Below is its long-term memory, today's notes, and its
most recent dream reports. Reflect on the day and produce three sections.

RULES
- Only propose DURABLE facts, preferences, or commitments (things that
  will still be true in a month). Skip trivia and one-off events.
- NEVER invent specifics (names, dates, numbers) that are not in the
  input. If unsure, put it in Open questions instead.
- Each candidate update is exactly one line, starting with `@@UPDATE@@ `.
  Example: `@@UPDATE@@ Prefers concise briefings with source links.`
- Keep the whole response under ~600 words.

## Candidate memory updates
(one @@UPDATE@@ line per durable fact, or "none")

## Alignment observations
(what worked today, any friction or drift from the user's stated
preferences, 2-5 bullets)

## Open questions
(things worth asking the user, 0-5 bullets; "none" if there are none)

--- MEMORY.md ---
{memory_md}

--- daily-notes.md ---
{daily}

--- recent dream reports ---
{dream_texts}
"""


def extract_updates(model_text: str) -> list[str]:
    """Pull @@UPDATE@@ one-liners out of the model's response."""
    updates = []
    for line in model_text.splitlines():
        line = line.strip()
        if line.startswith(UPDATE_MARKER):
            update = line[len(UPDATE_MARKER):].strip()
            if update and update not in updates:
                updates.append(update)
    return updates


def apply_updates(updates: list[str], memory_path: str) -> list[str]:
    """Append-only update of MEMORY.md. Returns the lines actually added.

    Never rewrites or deletes existing content. Lines already present
    (exact match) are skipped.
    """
    if not updates:
        return []
    with open(memory_path, encoding="utf-8") as f:
        existing = f.read()
    added = [u for u in updates if u not in existing]
    if not added:
        return []
    with open(memory_path, "a", encoding="utf-8") as f:
        if DREAM_SECTION not in existing:
            f.write(f"\n\n{DREAM_SECTION}\n")
        today = _dt.date.today().isoformat()
        for u in added:
            f.write(f"- [{today}] {u}\n")
    return added


def _report_path(today: _dt.date) -> str:
    base = os.path.join(DREAMS_DIR, today.isoformat() + ".md")
    if not os.path.exists(base):
        return base
    n = 2
    while True:
        candidate = os.path.join(DREAMS_DIR, f"{today.isoformat()}-{n}.md")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def load_provider_cfg() -> dict:
    """Provider config from config.yaml, else env-based defaults."""
    try:
        cfg = config_mod.load_config(os.path.join(REPO_ROOT, "config.yaml"))
        return cfg["provider"]
    except (FileNotFoundError, KeyError):
        return {
            "kind": os.environ.get("AGENT_PROVIDER", "openai_compatible"),
            "model": os.environ.get("AGENT_MODEL", "gpt-4o-mini"),
            "base_url": os.environ.get("AGENT_BASE_URL",
                                       "https://api.openai.com/v1"),
            "api_key": os.environ.get("AGENT_API_KEY", ""),
        }


def run_dream(dry_run: bool = False) -> dict:
    """Run one dreaming pass. Returns a summary dict."""
    today = _dt.date.today()
    prompt = build_prompt()
    provider_cfg = load_provider_cfg()

    if dry_run:
        print("=== DRY RUN: no model call, no writes ===\n")
        print(f"Would read: MEMORY.md, daily-notes.md, "
              f"{len(_recent_dreams())} recent dream report(s)")
        print(f"Would write: {os.path.join(DREAMS_DIR, today.isoformat() + '.md')}")
        print("Would append @@UPDATE@@ lines to MEMORY.md's "
              "'Dream updates (auto-appended)' section.\n")
        print("=== PROMPT (first 1500 chars) ===\n")
        print(prompt[:1500])
        return {"dry_run": True}

    provider = providers.from_config(provider_cfg)
    messages = [
        {"role": "system",
         "content": "You are the nightly reflection pass of a personal AI "
                    "agent. Follow the response format exactly."},
        {"role": "user", "content": prompt},
    ]
    response = provider.chat(messages, tools=[])
    model_text = response["choices"][0]["message"].get("content", "") or ""
    if not model_text.strip():
        raise RuntimeError("dream pass got an empty response from the model")

    updates = extract_updates(model_text)
    memory_path = os.path.join(MEMORY_DIR, "MEMORY.md")
    added = apply_updates(updates, memory_path)

    os.makedirs(DREAMS_DIR, exist_ok=True)
    report = (
        f"# Dream report — {today.isoformat()}\n\n"
        f"- Generated: {_dt.datetime.now(_dt.timezone.utc).isoformat()}\n"
        f"- Model: {provider_cfg.get('kind')}/{provider_cfg.get('model')}\n"
        f"- Candidate updates found: {len(updates)}\n"
        f"- Updates applied to MEMORY.md: {len(added)}\n"
    )
    if added:
        report += "\n## Changes applied to MEMORY.md\n" + "".join(
            f"- {u}\n" for u in added)
    else:
        report += "\n## Changes applied to MEMORY.md\n- none\n"
    report += f"\n---\n\n{model_text}\n"

    path = _report_path(today)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)

    summary = {"report": path, "updates_found": len(updates),
               "updates_applied": added}
    print(f"dream report written: {path}")
    print(f"updates found: {len(updates)}, applied: {len(added)}")
    for u in added:
        print(f"  + {u}")
    return summary


def self_test() -> None:
    import tempfile
    # update extraction
    text = "## Candidate memory updates\n@@UPDATE@@ Likes tea.\n@@UPDATE@@ Likes tea.\nno marker here\n@@UPDATE@@  \n"
    assert extract_updates(text) == ["Likes tea."], extract_updates(text)
    # apply_updates: append-only, deduped
    with tempfile.TemporaryDirectory() as d:
        mem = os.path.join(d, "MEMORY.md")
        with open(mem, "w") as f:
            f.write("# Memory\n\n- Likes tea.\n")
        assert apply_updates(["Likes tea."], mem) == []  # already present
        assert apply_updates(["Prefers mornings."], mem) == ["Prefers mornings."]
        with open(mem) as f:
            content = f.read()
        assert "Prefers mornings." in content
        assert content.count("Likes tea.") == 1, "must not duplicate"
        assert DREAM_SECTION in content
        # report path numbering
        dreams = os.path.join(d, "dreams")
        os.makedirs(dreams)
        open(os.path.join(dreams, "2026-09-24.md"), "w").close()
        global DREAMS_DIR
        old, DREAMS_DIR = DREAMS_DIR, dreams
        try:
            assert _report_path(_dt.date(2026, 9, 24)).endswith("2026-09-24-2.md")
        finally:
            DREAMS_DIR = old
    # prompt builds without a model
    p = build_prompt()
    assert "@@UPDATE@@" in p and "MEMORY.md" in p
    print("dream self-test OK")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Nightly dreaming pass")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and prompt; change nothing")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in self-test")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return
    try:
        run_dream(dry_run=args.dry_run)
    except Exception as e:
        print(f"dream pass failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
