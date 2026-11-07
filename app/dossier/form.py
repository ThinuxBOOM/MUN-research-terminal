"""Dossier form helpers and coverage checks (plan 10.1)."""
from __future__ import annotations

import json

from ..ingest import countries, topics


def clean_countries(raw: str | list) -> list[str]:
    if isinstance(raw, str):
        try:
            values = json.loads(raw) if raw.strip().startswith("[") else raw.split(",")
        except json.JSONDecodeError:
            values = raw.split(",")
    else:
        values = raw
    out = []
    for value in values:
        code = str(value).strip().upper()
        if code in countries.COUNTRIES and code not in out:
            out.append(code)
    return out


def coverage(conn, topic: str, country_codes: list[str]) -> dict:
    tid = topics.topic_id(conn, topic)
    if tid:
        docs = conn.execute("SELECT COUNT(DISTINCT doc_id) AS n FROM doc_topics WHERE topic_id = ?",
                            (tid,)).fetchone()["n"]
        vote_total = conn.execute(
            "SELECT COUNT(*) AS n FROM votes v JOIN doc_topics dt ON dt.doc_id = v.doc_id "
            "WHERE dt.topic_id = ?", (tid,)).fetchone()["n"]
        statements = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks c JOIN documents d ON d.id = c.doc_id "
            "WHERE c.speaker_country IS NOT NULL AND d.id IN "
            "(SELECT doc_id FROM doc_topics WHERE topic_id = ?)", (tid,)).fetchone()["n"]
    else:
        docs = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        vote_total = conn.execute("SELECT COUNT(*) AS n FROM votes").fetchone()["n"]
        statements = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE speaker_country IS NOT NULL").fetchone()["n"]

    gaps: list[str] = []
    for iso3 in country_codes:
        found = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks c WHERE c.speaker_country = ? "
            "AND (? IS NULL OR c.doc_id IN (SELECT doc_id FROM doc_topics WHERE topic_id = ?))",
            (iso3, tid, tid)).fetchone()["n"]
        if not found:
            gaps.append(iso3)

    if docs == 0:
        verdict, message = "empty", "No documents are tagged with this agenda yet."
    elif not tid:
        verdict, message = "thin", "This agenda is not mapped to a topic, so tagging is broad."
    elif statements < 3:
        verdict, message = "thin", "Few statements are in the library for this agenda."
    else:
        verdict, message = "good", "The library covers this agenda."
    return {"documents": docs, "votes": vote_total, "statements": statements,
            "countries_without_data": gaps, "verdict": verdict, "message": message}


def validate_form(data: dict) -> list[str]:
    errors = []
    if not data.get("name", "").strip():
        errors.append("Give the conference a name.")
    if not data.get("agenda", "").strip():
        errors.append("Enter the agenda item.")
    if data.get("my_country") not in countries.COUNTRIES:
        errors.append("Pick your country from the list.")
    return errors
