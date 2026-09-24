"""Tiny skill loader/search sketch.

Skills are directories with SKILL.md + frontmatter. Discovery is a
keyword search over name + description; the winner's full SKILL.md
is loaded into the agent's context for the task.
"""

from __future__ import annotations

import os
import re


def _parse_skill_md(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    front = {}
    body = text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                front[k.strip()] = v.strip()
        body = m.group(2)
    return {"frontmatter": front, "body": body, "path": path}


def discover(skills_dir: str) -> list[dict]:
    skills = []
    for entry in sorted(os.listdir(skills_dir)):
        md = os.path.join(skills_dir, entry, "SKILL.md")
        if os.path.isfile(md):
            skills.append(_parse_skill_md(md))
    return skills


def search(skills: list[dict], query: str, limit: int = 3) -> list[dict]:
    """Naive keyword rank over name + description. TODO: BM25/embeddings."""
    terms = query.lower().split()
    scored = []
    for s in skills:
        hay = (s["frontmatter"].get("name", "") + " " +
               s["frontmatter"].get("description", "")).lower()
        score = sum(hay.count(t) for t in terms)
        if score:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:limit]]


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    found = search(discover(here), " ".join(__import__("sys").argv[1:]))
    for s in found:
        print("=", s["frontmatter"].get("name"), s["path"])
