"""Ingestion pipeline: dedupe, detect, extract, parse, embed, index (plan 6).

Resumable and idempotent. Re-running an ingest never duplicates chunks, and a
document is skipped when the same SHA-256 or symbol is already stored.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from ..db import connect
from ..ingest import clean, countries, links, topics, votes
from ..ingest.chunker import context_text
from ..ingest.parsers import press, pv, report, resolution, treaty
from ..llm.client import LLMClient
from ..settings import CORPUS_INBOX, CORPUS_RAW
from ..vectorindex import save_embedding

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}

PARSERS = {
    "resolution": resolution.parse,
    "charter": treaty.parse,
    "treaty": treaty.parse,
    "rules": treaty.parse,
    "pv_record": pv.parse,
    "press_release": press.parse,
    "sg_report": report.parse,
    "icj": report.parse,
    "other": report.parse,
}


def sha256_of(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_from_filename(name: str) -> str | None:
    spaced = name.lower().replace("_", " ").replace("-", " ")
    if "charter" in spaced and "united nations" in spaced:
        return "UN CHARTER"
    stem = Path(name).stem
    stem = re.sub(r"[_\s]+", "/", stem, count=2)
    pv_match = re.match(r"^([SAE])/PV\.(\d+)$", stem, re.I)
    if pv_match:
        return f"{pv_match.group(1).upper()}/PV.{pv_match.group(2)}"
    match = re.match(r"^([SAE])/(RES|PV|CONF[\d.]*)/(.+)$", stem, re.I)
    if not match:
        return None
    organ, kind, rest = match.group(1).upper(), match.group(2).upper(), match.group(3)
    rest = rest.replace("_", "/")
    if kind in ("RES", "PV"):
        rest = re.sub(r"^(\d+[A-Za-z]?)\s*\(([^)]+)\)$", r"\1 (\2)", rest)
    return f"{organ}/{kind}/{rest}"


def symbol_from_text(paragraphs: list[str]) -> str | None:
    for text in paragraphs[:25]:
        match = re.search(r"\b([SA])/(RES|PV|CONF[\d.]*)/([A-Za-z0-9().\-/]+)", text)
        if match:
            raw = f"{match.group(1)}/{match.group(2)}/{match.group(3)}".rstrip(".,;")
            raw = re.sub(r"(\d+[A-Za-z]?)\(([^)]+)\)", r"\1 (\2)", raw)
            return raw
    return None


def detect_type(symbol: str | None, filename: str, text: str) -> str:
    hay = f"{symbol or ''} {filename}".upper()
    if "CHARTER" in hay:
        return "charter"
    if symbol and "/RES/" in symbol:
        return "resolution"
    if symbol and "/PV." in symbol.replace("/PV/", "/PV."):
        return "pv_record"
    if re.match(r"^SC/\d+", Path(filename).stem, re.I) or "PRESS RELEASE" in text[:400].upper():
        return "press_release"
    if re.search(r"\bA/CONF\.", hay) or "VIENNA CONVENTION" in hay or "ROME STATUTE" in hay:
        return "treaty"
    if re.match(r"^[SA]/\d{2,4}/", hay):
        return "sg_report"
    return "other"


def find_date(paragraphs: list[str]) -> str | None:
    for text in paragraphs[:20]:
        first = re.search(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b", text)
        if first and first.group(2).lower() in MONTHS:
            month = MONTHS[first.group(2).lower()]
            return f"{int(first.group(3)):04d}-{month:02d}-{int(first.group(1)):02d}"
        second = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", text)
        if second and second.group(1).lower() in MONTHS:
            month = MONTHS[second.group(1).lower()]
            return f"{int(second.group(3)):04d}-{month:02d}-{int(second.group(2)):02d}"
    return None


def organ_of(symbol: str | None) -> str:
    if not symbol:
        return "OTHER"
    if symbol.startswith("S/"):
        return "SC"
    if symbol.startswith("A/"):
        return "GA"
    return "OTHER"


def meeting_no(symbol: str | None) -> str | None:
    if not symbol:
        return None
    match = re.search(r"PV\.(\d+)", symbol)
    return match.group(1) if match else None


def ingest_file(conn, path: str | Path, doc_type: str | None = None,
                source_url: str | None = None, embed: bool = True) -> dict:
    path = Path(path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {path}"}
    digest = sha256_of(path)
    existing = conn.execute("SELECT id, symbol FROM documents WHERE sha256 = ?", (digest,)).fetchone()
    if existing:
        return {"status": "skipped", "message": "Already in the library (same file hash).",
                "doc_id": existing["id"], "symbol": existing["symbol"]}

    if path.suffix.lower() == ".pdf":
        pages = clean.extract_pages(path)
        paragraphs, metrics = clean.clean_pages(pages)
    else:
        paragraphs, metrics = clean.extract_text_file(path)
    if not paragraphs:
        return {"status": "error",
                "message": "No text found. This looks like a scanned PDF; OCR is not enabled."}

    quality = clean.parse_quality(metrics)
    symbol = symbol_from_filename(path.name) or symbol_from_text(paragraphs)
    merged = "\n".join(paragraphs[:60])
    kind = doc_type or detect_type(symbol, path.name, merged)
    date = find_date(paragraphs)
    meta = {
        "symbol": symbol,
        "doc_type": kind,
        "organ": organ_of(symbol),
        "date": date,
        "meeting_no": meeting_no(symbol),
        "title": None,
    }
    chunks = PARSERS.get(kind, report.parse)(paragraphs, meta)

    if symbol:
        clash = conn.execute("SELECT id FROM documents WHERE symbol = ?", (symbol,)).fetchone()
        if clash:
            return {"status": "skipped", "message": f"Symbol {symbol} is already in the library.",
                    "doc_id": clash["id"], "symbol": symbol}

    title = meta.get("title") or (chunks[0]["text"][:180] if chunks else path.stem)
    status = "ok" if quality >= 0.5 else "low_quality"
    cursor = conn.execute(
        "INSERT INTO documents(symbol, title, doc_type, organ, date, year, source_path, source_url, "
        "sha256, parse_quality, status, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (symbol, title, kind, meta["organ"], date, int(date[:4]) if date else None,
         str(path), source_url, digest, quality, status, datetime.now().isoformat(timespec="seconds")),
    )
    doc_id = int(cursor.lastrowid)

    for ordinal, chunk in enumerate(chunks):
        conn.execute(
            "INSERT INTO chunks(doc_id, ordinal, kind, label, speaker_name, speaker_country, "
            "meeting_no, date, text, token_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (doc_id, ordinal, chunk["kind"], chunk["label"], chunk.get("speaker_name"),
             chunk.get("speaker_country"), chunk.get("meeting_no") or meta["meeting_no"],
             chunk.get("date") or date, chunk["text"], chunk["token_count"]),
        )
    conn.commit()

    conn.execute("UPDATE documents SET title = ? WHERE id = ?",
                 (meta.get("title") or title, doc_id))
    conn.commit()

    embedded = 0
    if embed:
        embedded = embed_document(conn, doc_id)
    created = links.build_doc_links(conn, doc_id, chunks, meta["organ"])
    tags = topics.tag_document(conn, doc_id, "\n".join(c["text"] for c in chunks))
    conn.commit()

    return {
        "status": "ingested",
        "doc_id": doc_id,
        "symbol": symbol,
        "doc_type": kind,
        "date": date,
        "chunks": len(chunks),
        "quality": round(quality, 2),
        "flagged": status == "low_quality",
        "embedded": embedded,
        "links": created,
        "topics": tags,
    }


def embed_document(conn, doc_id: int) -> int:
    """Embed every chunk of one document; safe to re-run."""
    rows = conn.execute(
        "SELECT c.id, c.text, c.label, d.symbol, d.organ, d.date FROM chunks c "
        "JOIN documents d ON d.id = c.doc_id WHERE c.doc_id = ? ORDER BY c.ordinal",
        (doc_id,)).fetchall()
    if not rows:
        return 0
    client = LLMClient()
    texts = [context_text(row["symbol"] or "", row["label"] or "", row["organ"] or "",
                          row["date"] or "", row["text"]) for row in rows]
    vectors = client.embed(texts)
    for row, vector in zip(rows, vectors):
        save_embedding(conn, row["id"], vector)
    conn.commit()
    return len(rows)


def backfill_embeddings(conn) -> int:
    rows = conn.execute(
        "SELECT DISTINCT c.doc_id FROM chunks c LEFT JOIN chunk_vec v ON v.chunk_id = c.id "
        "WHERE v.chunk_id IS NULL").fetchall()
    total = 0
    for row in rows:
        total += embed_document(conn, row["doc_id"])
    return total


def ingest_folder(conn, folder: str | Path) -> list[dict]:
    folder = Path(folder)
    results = []
    if not folder.exists():
        return results
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in (".pdf", ".txt", ".md"):
            try:
                results.append(ingest_file(conn, path))
            except Exception as exc:  # noqa: BLE001
                results.append({"status": "error", "file": path.name, "message": str(exc)})
    return results


def seed_reference_data(conn) -> None:
    countries.seed(conn)
    topics.seed(conn)


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = argv or sys.argv[1:]
    conn = connect()
    seed_reference_data(conn)
    folders = [CORPUS_RAW]
    if not argv:
        folders.append(CORPUS_INBOX)
    for folder in folders:
        print(f"Reading {folder} ...")
        for result in ingest_folder(conn, folder):
            if result["status"] == "ingested":
                print(f"  OK   {result['symbol'] or result['doc_id']}: {result['chunks']} chunks, "
                      f"{result['links']} links, quality {result['quality']}")
            elif result["status"] == "skipped":
                print(f"  SKIP {result.get('symbol') or result.get('file')}: {result['message']}")
            else:
                print(f"  FAIL {result.get('file', '')}: {result['message']}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
