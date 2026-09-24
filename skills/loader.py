"""Skill loader + BM25 semantic search.

Skills are directories with SKILL.md + frontmatter. Discovery builds a
BM25 index over name + description + body text; ``rank_skills(query)``
returns the best matches with scores. The winner's full SKILL.md is
loaded into the agent's context for the task.

BM25 is implemented in pure Python (no numpy). Name terms are weighted
heavier than body terms by indexing the name multiple times.
"""

from __future__ import annotations

import math
import os
import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


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


def _doc_text(skill: dict) -> str:
    """Name-heavy document text: name x3, description x2, body x1."""
    name = skill["frontmatter"].get("name", "")
    desc = skill["frontmatter"].get("description", "")
    return f"{name} {name} {name} {desc} {desc} {skill['body']}"


class BM25Index:
    """Okapi BM25 over a corpus of skill documents. Pure Python."""

    def __init__(self, skills: list[dict], k1: float = 1.5, b: float = 0.75):
        self.skills = skills
        self.k1 = k1
        self.b = b
        self.doc_tokens: list[list[str]] = []
        self.doc_len: list[int] = []
        self.df: dict[str, int] = {}   # term -> # docs containing it
        self.tf: list[dict[str, int]] = []  # per-doc term frequencies
        for skill in skills:
            tokens = _tokenize(_doc_text(skill))
            self.doc_tokens.append(tokens)
            self.doc_len.append(len(tokens))
            counts: dict[str, int] = {}
            for t in tokens:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in counts:
                self.df[t] = self.df.get(t, 0) + 1
        self.n = len(skills)
        self.avgdl = sum(self.doc_len) / self.n if self.n else 0.0

    def _idf(self, term: str) -> float:
        # Robertson/Sparck-Jones IDF with +1 smoothing (always >= 0).
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_idx: int) -> float:
        total = 0.0
        dl = self.doc_len[doc_idx]
        norm = 1 - self.b + self.b * (dl / self.avgdl) if self.avgdl else 1.0
        for term in _tokenize(query):
            f = self.tf[doc_idx].get(term, 0)
            if not f:
                continue
            total += (self._idf(term)
                      * f * (self.k1 + 1) / (f + self.k1 * norm))
        return total

    def rank(self, query: str, top_k: int = 3) -> list[tuple[float, dict]]:
        scored = [(self.score(query, i), self.skills[i])
                  for i in range(self.n)]
        scored = [(s, sk) for s, sk in scored if s > 0]
        scored.sort(key=lambda x: -x[0])
        return scored[:top_k]


def build_index(skills: list[dict]) -> BM25Index:
    """Build a BM25 index over discovered skills."""
    return BM25Index(skills)


def rank_skills(query: str, skills: list[dict] | None = None,
                skills_dir: str | None = None,
                top_k: int = 3) -> list[tuple[float, dict]]:
    """Rank skills for a query. Returns [(score, skill), ...], best first.

    Pass either a discovered skill list or a skills_dir (defaults to the
    directory this file lives in).
    """
    if skills is None:
        if skills_dir is None:
            skills_dir = os.path.dirname(os.path.abspath(__file__))
        skills = discover(skills_dir)
    return build_index(skills).rank(query, top_k)


def search(skills: list[dict], query: str, limit: int = 3) -> list[dict]:
    """Backward-compatible search: ranked skill dicts, best first."""
    return [skill for _, skill in rank_skills(query, skills=skills, top_k=limit)]


def load_best(query: str, skills_dir: str | None = None) -> dict | None:
    """Load the full SKILL.md text of the best match, or None."""
    ranked = rank_skills(query, skills_dir=skills_dir, top_k=1)
    if not ranked:
        return None
    skill = ranked[0][1]
    with open(skill["path"], encoding="utf-8") as f:
        return f.read()


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        specs = {
            "notes": ("notes", "take and organize notes",
                      "How to capture meeting notes, daily notes, and journal entries."),
            "email": ("email-triage", "triage an email inbox",
                      "Rules for sorting email, drafting replies, and unsubscribing."),
            "deploy": ("deploy", "deploy a static website",
                       "Build and rsync a static site to a VPS over ssh."),
        }
        for dirname, (name, desc, body) in specs.items():
            os.makedirs(os.path.join(d, dirname))
            with open(os.path.join(d, dirname, "SKILL.md"), "w") as f:
                f.write(f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n")
        skills = discover(d)
        assert len(skills) == 3
        ranked = rank_skills("how do I take meeting notes?", skills=skills, top_k=3)
        assert ranked, "expected at least one match"
        assert ranked[0][1]["frontmatter"]["name"] == "notes", \
            f"wrong winner: {ranked[0][1]['frontmatter'].get('name')}"
        assert ranked[0][0] >= ranked[-1][0], "scores not descending"
        ranked = rank_skills("deploy website ssh", skills=skills, top_k=1)
        assert ranked[0][1]["frontmatter"]["name"] == "deploy"
        ranked = rank_skills("quantum banana toaster", skills=skills, top_k=3)
        assert ranked == [], f"expected no matches, got {ranked}"
        # backward-compat search()
        found = search(skills, "email inbox replies", limit=2)
        assert found[0]["frontmatter"]["name"] == "email-triage"
        assert load_best("meeting notes", d).startswith("---")
    print("skills self-test OK")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        for score, s in rank_skills(" ".join(sys.argv[1:])):
            print(f"{score:7.3f}  {s['frontmatter'].get('name')}  {s['path']}")
    else:
        self_test()
