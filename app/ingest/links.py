"""Regex link extraction and typed graph edges (plan 6.5).

Regex edges are accepted automatically but remain reviewable. LLM-suggested
edges are always created with status='pending' and are only used in retrieval
after the user accepts them.
"""
from __future__ import annotations

import re

SYMBOL_REF = re.compile(r"\b([SAE])/RES/(\d{1,4})(?:\s*\(([IVXLC]+|\d{4})\))?", re.I)
RES_WORD = re.compile(r"\bresolutions?\s+(\d{1,4})\s*(?:\((\d{4})\))?", re.I)
ARTICLE_REF = re.compile(r"\bArticle\s+(\d{1,3}[A-Za-z]?)\b", re.I)
CHAPTER_REF = re.compile(r"\bChapter\s+(VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV)\b", re.I)

REL_WORDS = [
    (re.compile(r"\brecall(?:ing|s|ed)?\b", re.I), "recalls"),
    (re.compile(r"\breaffirm(?:ing|s|ed)?\b", re.I), "reaffirms"),
    (re.compile(r"\bdecides to extend\b|\bextends?\b", re.I), "extends"),
    (re.compile(r"\bamends?\b", re.I), "amends"),
    (re.compile(r"\bsupersed(?:es|ed|ing)\b|\breplaces?\b", re.I), "supersedes"),
    (re.compile(r"\bacting under Chapter VII\b", re.I), "cites"),
    (re.compile(r"\btakes? note\b|\bnoting\b", re.I), "related"),
]

# Relations that can link a bare mention to the agenda topic.
CHAPTER_TARGET = {
    "VI": ("Chapter VI", "pacific settlement"),
    "VII": ("Chapter VII", "enforcement"),
}


def _relation(prefix: str) -> str:
    for pattern, rel in REL_WORDS:
        if pattern.search(prefix):
            return rel
    return "cites"


def find_symbols(text: str) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for organ, number, year in SYMBOL_REF.findall(text or ""):
        out.append((f"{organ.upper()}/RES/{number}", year))
    for number, year in RES_WORD.findall(text or ""):
        out.append((number, year))
    return out


def resolve_symbol(conn, number: str, year: str | None) -> int | None:
    """Find a document by resolution number (and year when given)."""
    if "/" in number:
        row = conn.execute("SELECT id FROM documents WHERE symbol LIKE ?",
                           (f"%{number}%",)).fetchone()
        if row and (not year or year.isdigit() is False or str(year) in ""):
            return row["id"]
    pattern = f"%/{number}%"
    rows = conn.execute("SELECT id, symbol FROM documents WHERE symbol LIKE ?", (pattern,)).fetchall()
    if year:
        for row in rows:
            if f"({year})" in row["symbol"]:
                return row["id"]
    return rows[0]["id"] if rows else None


def ensure_stub(conn, number: str, year: str | None, organ: str = "SC") -> int:
    prefix = number if "/" in number else f"{organ}/RES/{number}"
    symbol = f"{prefix} ({year})" if year and "/" in prefix else prefix
    row = conn.execute("SELECT id FROM documents WHERE symbol = ?", (symbol,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO documents(symbol, title, doc_type, organ, year, status) "
        "VALUES (?, ?, 'resolution', ?, ?, 'stub')",
        (symbol, f"Referenced resolution {symbol} (not yet downloaded)", organ,
         int(year) if year and str(year).isdigit() else None),
    )
    return int(cursor.lastrowid)


def _insert_edge(conn, src_id: int, dst_id: int, rel: str, evidence_chunk_id: int | None,
                 origin: str = "regex", confidence: float = 0.9,
                 status: str = "accepted") -> bool:
    if src_id == dst_id:
        return False
    exists = conn.execute(
        "SELECT id FROM edges WHERE src_type='doc' AND src_id=? AND dst_type='doc' "
        "AND dst_id=? AND rel=?", (src_id, dst_id, rel)).fetchone()
    if exists:
        return False
    conn.execute(
        "INSERT INTO edges(src_type, src_id, dst_type, dst_id, rel, origin, confidence, "
        "status, evidence_chunk_id) VALUES ('doc', ?, 'doc', ?, ?, ?, ?, ?, ?)",
        (src_id, dst_id, rel, origin, confidence, status, evidence_chunk_id),
    )
    return True


def build_doc_links(conn, doc_id: int, chunks: list[dict], organ: str = "SC") -> int:
    """Extract references from the document text and create accepted edges."""
    created = 0
    seen: set[tuple[int, str]] = set()
    for chunk in chunks:
        text = chunk["text"]
        for number, year in find_symbols(text):
            target = resolve_symbol(conn, number, year)
            if target is None:
                target = ensure_stub(conn, number, year, "S" if len(number) <= 4 else organ)
            if target == doc_id:
                continue
            match = SYMBOL_REF.search(text) or RES_WORD.search(text)
            prefix = text[max(0, (match.start() if match else 0) - 120): (match.start() if match else 0)]
            rel = _relation(prefix)
            if (target, rel) in seen:
                continue
            seen.add((target, rel))
            if _insert_edge(conn, doc_id, target, rel, None):
                created += 1
    conn.commit()
    return created


def neighbours(conn, doc_id: int, rel_filter: tuple[str, ...] | None = None,
               accepted_only: bool = True) -> list[dict]:
    sql = ("SELECT e.rel, e.dst_id AS other_id, e.src_id, d.symbol, d.title, d.doc_type, d.date, "
           "e.status, e.confidence FROM edges e JOIN documents d ON d.id = e.dst_id "
           "WHERE e.src_type='doc' AND e.src_id=?")
    params: list = [doc_id]
    if accepted_only:
        sql += " AND e.status='accepted'"
    if rel_filter:
        sql += f" AND e.rel IN ({','.join('?' * len(rel_filter))})"
        params.extend(rel_filter)
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def shortest_path(conn, src_id: int, dst_id: int, max_depth: int = 3) -> list[dict] | None:
    """BFS over accepted edges in both directions."""
    if src_id == dst_id:
        return []
    queue: list[list[dict]] = [[]]
    visited = {src_id}
    frontier = [src_id]
    for _ in range(max_depth):
        next_frontier = []
        for node in frontier:
            prefix = [hop for hop in queue.pop(0)] if queue else []
            rows = conn.execute(
                "SELECT rel, src_id, dst_id, status FROM edges "
                "WHERE status='accepted' AND (src_id = ? OR dst_id = ?)", (node, node)
            ).fetchall()
            for row in rows:
                other = row["dst_id"] if row["src_id"] == node else row["src_id"]
                if other in visited:
                    continue
                hop = {"from": node, "to": other, "rel": row["rel"]}
                path = prefix + [hop]
                if other == dst_id:
                    return path
                visited.add(other)
                next_frontier.append(other)
                queue.append(path)
        frontier = next_frontier
        if not frontier:
            break
    return None
