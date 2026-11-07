"""Query router: rules first, LLM only as a fallback (plan 7.1)."""
from __future__ import annotations

import re

from ..ingest import countries

MODE_WORDS = [
    ("stance", r"\b(stance|position|positions|policy|view of|views on|where does|how did .* vote)\b"),
    ("connect", r"\b(connect|connection|link|linked|relation between|relate|compare)\b"),
    ("counter", r"\b(counter|counterargument|rebut|rebuttal|attack|criticis|criticiz|oppose)\b"),
    ("argue", r"\b(argue|argument|talking point|justify|defend|make the case)\b"),
    ("check", r"\b(conflict|conflicts|duplicate|overlap|consistent with)\b"),
]
SYMBOL_RE = re.compile(r"\b([SA])/(?:RES|PV)/(\d{1,4})(?:\s*\((\d{4})\))?", re.I)
ARTICLE_RE = re.compile(r"\bArticle\s+(\d{1,3}[A-Za-z]?)\b", re.I)
CHAPTER_RE = re.compile(r"\bChapter\s+(VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV)\b", re.I)

# Naming a document in the question scopes an article reference to that kind of text.
DOC_HINTS = {
    "charter": "charter",
    "rome statute": "treaty",
    "vienna convention": "treaty",
    "iccpcr": "resolution",
    "iccpr": "resolution",
    "universal declaration": "resolution",
}


def detect_country(text: str) -> str | None:
    """Longest alias match wins so 'United States' beats 'States'."""
    lowered = (text or "").lower()
    best: tuple[int, str] | None = None
    for iso3, (name, aliases) in countries.COUNTRIES.items():
        for label in [name, *aliases]:
            if len(label) < 3:
                continue
            if re.search(r"\b" + re.escape(label.lower()) + r"\b", lowered):
                if best is None or len(label) > best[0]:
                    best = (len(label), iso3)
    return best[1] if best else None


def detect_symbols(text: str) -> list[str]:
    return [f"{organ.upper()}/RES/{number}" + (f" ({year})" if year else "")
            for organ, number, year in SYMBOL_RE.findall(text or "")]


def detect_article(text: str) -> str | None:
    match = ARTICLE_RE.search(text or "")
    return match.group(1) if match else None


def detect_mode(text: str) -> str:
    lowered = (text or "").lower()
    for mode, pattern in MODE_WORDS:
        if re.search(pattern, lowered):
            return mode
    return "evidence"


def route(conn, question: str, conference: dict | None = None) -> dict:
    text = question or ""
    mode = detect_mode(text)
    iso3 = detect_country(text)
    symbols = detect_symbols(text)
    article = detect_article(text)
    topic_id = None
    filters: dict = {}
    if conference:
        topic_id = conference.get("topic_id")
        if iso3 is None and mode == "stance":
            iso3 = conference.get("my_country")
    if iso3:
        filters["country"] = iso3
    if topic_id:
        filters["topic_id"] = topic_id
    if article:
        lowered = text.lower()
        for hint, doc_type in DOC_HINTS.items():
            if hint in lowered:
                filters["doc_type"] = doc_type
                break
        else:
            # In MUN debate a bare article reference means the UN Charter, so a
            # question about "Article 51" must not mix in other treaties' Article 51.
            filters["doc_type"] = "charter"
    return {
        "mode": mode,
        "country": iso3,
        "symbols": symbols,
        "article": article,
        "chapter": (CHAPTER_RE.search(text).group(1) if CHAPTER_RE.search(text) else None),
        "topic_id": topic_id,
        "filters": filters,
        "exact": bool(symbols or article or CHAPTER_RE.search(text)),
    }


def exact_ids(conn, routed: dict, filters: dict | None = None) -> list[int]:
    """Shortcut: quoted symbol/article/chapter hits come first."""
    doc_type = (filters or {}).get("doc_type")
    ids: list[int] = []
    for symbol in routed.get("symbols", []):
        rows = conn.execute("SELECT id FROM documents WHERE upper(symbol) = upper(?)",
                            (symbol,)).fetchall()
        if not rows:
            rows = conn.execute("SELECT id FROM documents WHERE symbol LIKE ?",
                                (f"%{symbol}%",)).fetchall()
        for row in rows:
            ids.extend(r["id"] for r in conn.execute(
                "SELECT id FROM chunks WHERE doc_id = ? ORDER BY ordinal LIMIT 4", (row["id"],)))
    article = routed.get("article")
    if article:
        rows = conn.execute(
            "SELECT c.id FROM chunks c JOIN documents d ON d.id = c.doc_id "
            "WHERE lower(c.label) IN (?, ?) AND d.doc_type IN ('charter','treaty') "
            "AND (? IS NULL OR d.doc_type = ?) "
            "ORDER BY CASE d.doc_type WHEN 'charter' THEN 0 ELSE 1 END",
            (f"art. {article}".lower(), f"article {article}".lower(), doc_type, doc_type)
        ).fetchall()
        ids.extend(row["id"] for row in rows)
    chapter = routed.get("chapter")
    if chapter:
        rows = conn.execute(
            "SELECT id FROM chunks WHERE text LIKE ? AND doc_type IN ('charter','treaty') "
            "ORDER BY ordinal LIMIT 6", (f"%Chapter {chapter}%",)).fetchall()
        ids.extend(row["id"] for row in rows)
    # De-duplicate, keep order.
    seen: set[int] = set()
    ordered = []
    for chunk_id in ids:
        if chunk_id not in seen:
            seen.add(chunk_id)
            ordered.append(chunk_id)
    return ordered[:12]
