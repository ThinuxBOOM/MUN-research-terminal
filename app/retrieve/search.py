"""Hybrid search: FTS5 BM25 plus vector cosine, with structured filters (plan 7.3)."""
from __future__ import annotations

from ..db import connect
from ..settings import config
from ..textutil import clean_term, content_words
from ..vectorindex import cosine_search

DOC_TYPES = ["charter", "treaty", "resolution", "pv_record", "press_release",
             "sg_report", "icj", "rules", "position", "other"]


def _filter_sql(filters: dict) -> tuple[list[str], list]:
    where: list[str] = []
    params: list = []
    if filters.get("doc_type"):
        where.append("d.doc_type = ?")
        params.append(filters["doc_type"])
    if filters.get("organ"):
        where.append("d.organ = ?")
        params.append(filters["organ"])
    if filters.get("year_from"):
        where.append("d.year >= ?")
        params.append(int(filters["year_from"]))
    if filters.get("year_to"):
        where.append("d.year <= ?")
        params.append(int(filters["year_to"]))
    if filters.get("topic_id"):
        where.append("d.id IN (SELECT doc_id FROM doc_topics WHERE topic_id = ?)")
        params.append(int(filters["topic_id"]))
    if filters.get("country"):
        where.append("c.speaker_country = ?")
        params.append(filters["country"])
    return where, params


def allowed_chunk_ids(conn, filters: dict) -> set[int] | None:
    where, params = _filter_sql(filters or {})
    if not where:
        return None
    sql = ("SELECT c.id FROM chunks c JOIN documents d ON d.id = c.doc_id WHERE "
           + " AND ".join(where))
    return {row["id"] for row in conn.execute(sql, params).fetchall()}


def fts_query(text: str) -> str:
    terms = [clean_term(w) for w in content_words(text)]
    terms = [t for t in terms if len(t) > 1]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"*' for t in terms[:14])


def fts_search(conn, query: str, top_k: int | None = None,
               allowed: set[int] | None = None) -> list[tuple[int, float]]:
    top_k = top_k or int(config()["retrieval"]["fts_top_k"])
    match = fts_query(query)
    if not match:
        return []
    try:
        rows = conn.execute(
            "SELECT rowid AS id, bm25(chunks_fts) AS score FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?",
            (match, top_k * 4),
        ).fetchall()
    except Exception:
        return []
    out = [(row["id"], -float(row["score"])) for row in rows
           if allowed is None or row["id"] in allowed]
    return out[:top_k]


def vector_search(conn, query_vector, top_k: int | None = None,
                  allowed: set[int] | None = None) -> list[tuple[int, float]]:
    top_k = top_k or int(config()["retrieval"]["vec_top_k"])
    try:
        return cosine_search(conn, query_vector, top_k=top_k, allowed=allowed)
    except Exception:
        return []


def load_chunks(conn, chunk_ids: list[int]) -> list[dict]:
    if not chunk_ids:
        return []
    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"SELECT c.*, d.symbol, d.title, d.doc_type, d.organ, d.date AS doc_date, d.year "
        f"FROM chunks c JOIN documents d ON d.id = c.doc_id WHERE c.id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    by_id = {row["id"]: dict(row) for row in rows}
    ordered = []
    for chunk_id in chunk_ids:
        if chunk_id in by_id:
            item = by_id[chunk_id]
            item["date"] = item.get("date") or item.get("doc_date")
            ordered.append(item)
    return ordered


def statements_for_country(conn, iso3: str, topic_id: int | None = None,
                           limit: int = 15) -> list[dict]:
    sql = ("SELECT c.*, d.symbol, d.title, d.doc_type, d.organ, d.date AS doc_date "
           "FROM chunks c JOIN documents d ON d.id = c.doc_id "
           "WHERE c.speaker_country = ?")
    params: list = [iso3]
    if topic_id:
        sql += " AND d.id IN (SELECT doc_id FROM doc_topics WHERE topic_id = ?)"
        params.append(topic_id)
    sql += " ORDER BY COALESCE(c.date, d.date) DESC LIMIT ?"
    params.append(limit)
    rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    for row in rows:
        row["date"] = row.get("date") or row.get("doc_date")
    return rows


def recent_years(conn) -> tuple[int | None, int | None]:
    row = conn.execute("SELECT MIN(year) AS lo, MAX(year) AS hi FROM documents "
                       "WHERE year IS NOT NULL").fetchone()
    return (row["lo"], row["hi"]) if row else (None, None)


def open_conn():
    return connect()
