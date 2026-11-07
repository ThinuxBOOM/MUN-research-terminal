"""Small text helpers shared by ingestion, retrieval and guardrails."""
from __future__ import annotations

import re

TOKEN_CHARS = 4.0  # rough English estimate; the guardrail budgets stay conservative


def est_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / TOKEN_CHARS))


def clamp_tokens(text: str, budget: int) -> str:
    limit = int(budget * TOKEN_CHARS)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("\n"))
    return (cut[:stop] if stop > limit * 0.6 else cut).rstrip() + " …"


def normalize_ws(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\ufb01", "fi").replace("\ufb02", "fl")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]{1,}")


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text or "")]


STOPWORDS = set("""a an the and or of to in on for with by at from as is are was were be been
this that these those it its their his her which who whom what when where how does do did
not no nor but if then than also such any all more most other into over under about""".split())


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS and len(w) > 1]


def clean_term(text: str) -> str:
    """FTS5-safe token."""
    return re.sub(r"[^A-Za-z0-9]", "", text or "")


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text or "")
    return [p.strip() for p in parts if p.strip()]
