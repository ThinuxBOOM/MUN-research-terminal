"""Graph expansion and connection paths over accepted edges (plan 7.5)."""
from __future__ import annotations

from ..settings import config


def expand(conn, seeds: list[dict], hops: int | None = None,
           per_seed: int | None = None) -> list[dict]:
    """Add chunks from accepted 1-hop neighbours of the top seed documents."""
    cfg = config()["retrieval"]
    hops = hops or int(cfg["graph_hops"])
    per_seed = per_seed or int(cfg["graph_per_seed"])
    seed_docs = []
    for chunk in seeds[: int(cfg["graph_seed_chunks"])]:
        if chunk.get("doc_id") and chunk["doc_id"] not in seed_docs:
            seed_docs.append(chunk["doc_id"])

    added: list[dict] = []
    seen_chunks = {chunk["id"] for chunk in seeds}
    for doc_id in seed_docs:
        rows = conn.execute(
            "SELECT e.rel, e.dst_id AS other_id FROM edges e "
            "WHERE e.status='accepted' AND e.src_type='doc' AND e.src_id=? "
            "AND e.rel IN ('recalls','reaffirms','extends','amends','supersedes','cites') "
            "LIMIT ?", (doc_id, per_seed),
        ).fetchall()
        for row in rows:
            chunk = conn.execute(
                "SELECT c.*, d.symbol, d.title, d.doc_type, d.organ, d.date AS doc_date "
                "FROM chunks c JOIN documents d ON d.id = c.doc_id "
                "WHERE c.doc_id = ? ORDER BY c.ordinal LIMIT 1", (row["other_id"],),
            ).fetchone()
            if not chunk or chunk["id"] in seen_chunks:
                continue
            item = dict(chunk)
            item["date"] = item.get("date") or item.get("doc_date")
            item["score"] = 0.05
            item["via"] = row["rel"]
            item["via_doc"] = doc_id
            seen_chunks.add(item["id"])
            added.append(item)
    return added


def neighbours(conn, doc_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT e.rel, e.status, e.confidence, e.origin, d.id, d.symbol, d.title, d.date "
        "FROM edges e JOIN documents d ON d.id = e.dst_id "
        "WHERE e.src_type='doc' AND e.src_id=? ORDER BY d.date DESC", (doc_id,)).fetchall()
    return [dict(row) for row in rows]


def path_between(conn, src_id: int, dst_id: int, max_depth: int = 3) -> list[dict] | None:
    from ..ingest.links import shortest_path

    return shortest_path(conn, src_id, dst_id, max_depth)


def path_narrative(conn, path: list[dict]) -> list[dict]:
    """Decorate each hop with document symbols for the UI and the prompt."""
    hops = []
    for hop in path:
        src = conn.execute("SELECT symbol, title, date FROM documents WHERE id = ?",
                           (hop["from"],)).fetchone()
        dst = conn.execute("SELECT symbol, title, date FROM documents WHERE id = ?",
                           (hop["to"],)).fetchone()
        hops.append({
            "rel": hop["rel"],
            "from": dict(src) if src else {"symbol": str(hop["from"])},
            "to": dict(dst) if dst else {"symbol": str(hop["to"])},
        })
    return hops


def find_doc(conn, text: str) -> dict | None:
    """Resolve a typed resolution number or symbol to a document row."""
    import re

    text = (text or "").strip()
    if not text:
        return None
    row = conn.execute("SELECT * FROM documents WHERE upper(symbol) = upper(?)", (text,)).fetchone()
    if row:
        return dict(row)
    match = re.search(r"(\d{1,4})\s*(?:\((\d{4})\))?", text)
    if not match:
        return None
    number, year = match.group(1), match.group(2)
    rows = conn.execute("SELECT * FROM documents WHERE symbol LIKE ?", (f"%/{number}%",)).fetchall()
    if not rows:
        rows = conn.execute("SELECT * FROM documents WHERE symbol LIKE ?",
                            (f"%{number}%",)).fetchall()
    if year:
        for candidate in rows:
            if f"({year})" in (candidate["symbol"] or ""):
                return dict(candidate)
    return dict(rows[0]) if rows else None
