"""Automatic dossier checks (task 7).

Hard failures (the function reports them and the CLI exits 1):
  - a dossier section is missing or failed;
  - a resolution reference has the wrong year or does not exist in the library;
  - the speech cites fewer than three distinct sources;
  - a POI card has fewer than two evidence items.

Soft findings (reported, not fatal): factual-looking sentences with no citation marker.
"""
from __future__ import annotations

import re

from ..llm import guards
from ..textutil import sentences

SECTIONS = ["background", "legal", "history", "profiles", "blocs", "position",
            "counter", "speech", "working_paper", "pois"]
NARRATIVE = {"background", "counter", "position", "speech"}
CITATION = re.compile(r"\[(S\d+|(?:S|A)/RES/[^\]]+|UN CHARTER[^\]]*)\]", re.I)
SYMBOL = re.compile(r"\b(?:S|A)/RES/\d{1,4}\s*(?:\([^)]+\))?|\bUN CHARTER\b", re.I)


def _section_map(conn, conference_id: int) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT * FROM dossier_sections WHERE conference_id = ? ORDER BY id",
        (conference_id,)).fetchall()
    return {row["section"]: dict(row) for row in rows}


def check(conn, conference_id: int) -> dict:
    sections = _section_map(conn, conference_id)
    known = {row["symbol"] for row in conn.execute(
        "SELECT symbol FROM documents WHERE symbol IS NOT NULL").fetchall()}
    failures: list[str] = []
    warnings: list[str] = []

    for key in SECTIONS:
        row = sections.get(key)
        if not row:
            failures.append(f"{key}: section missing")
            continue
        if row.get("status") == "error":
            failures.append(f"{key}: section failed to build")

    for key, row in sections.items():
        text = row.get("content_md") or ""
        bad = guards.validate_resolution_refs(text, known)
        for reference in bad:
            failures.append(f"{key}: reference not in library with that year: {reference}")

    speech = (sections.get("speech") or {}).get("content_md") or ""
    speech_sources = {match.group(0) for match in SYMBOL.finditer(speech)}
    if len(speech_sources) < 3:
        failures.append(f"speech: cites {len(speech_sources)} distinct sources (needs 3)")
    conf = conn.execute("SELECT speech_seconds FROM conferences WHERE id = ?",
                        (conference_id,)).fetchone()
    target = ((conf["speech_seconds"] or 90) if conf else 90) * 130 / 60
    body = speech.split("### Sources")[0]
    spoken = [line for line in body.splitlines()
              if line.strip() and not line.lstrip().startswith(("#", "_"))]
    words = len(" ".join(spoken).split())
    if not target * 0.9 <= words <= target * 1.1:
        failures.append(f"speech: {words} words against a target of {int(target)} (\u00b110%)")

    pois = (sections.get("pois") or {}).get("content_md") or ""
    cards = re.split(r"^### ", pois, flags=re.M)[1:]
    for card in cards:
        name = card.splitlines()[0].strip()
        quotes = [line for line in card.splitlines() if line.strip().startswith(">")]
        if "No strong angle" in card:
            continue
        if len(quotes) < 2:
            failures.append(f"pois: card '{name}' has {len(quotes)} evidence item(s), needs 2")

    for key in NARRATIVE:
        text = (sections.get(key) or {}).get("content_md") or ""
        if not text or text.strip().startswith(("No documents", "Not enough", "No statements")):
            continue
        uncited = [s for s in sentences(text)
                   if len(s.split()) > 6 and not CITATION.search(s) and not SYMBOL.search(s)]
        total = max(1, len([s for s in sentences(text) if len(s.split()) > 6]))
        if uncited:
            warnings.append(f"{key}: {len(uncited)}/{total} factual sentences without a citation")

    return {"ok": not failures, "failures": failures, "warnings": warnings,
            "sections": {key: (row.get("status") if row else "missing")
                         for key, row in ((k, sections.get(k)) for k in SECTIONS)}}


def main(argv: list[str] | None = None) -> int:
    import sys

    from ..db import connect

    argv = argv or sys.argv[1:]
    conference_id = int(argv[0]) if argv else 1
    conn = connect()
    try:
        result = check(conn, conference_id)
    finally:
        conn.close()
    print(f"Dossier checks for conference {conference_id}")
    for key, status in result["sections"].items():
        print(f"  {key:<14} {status}")
    for warning in result["warnings"]:
        print("  WARN  " + warning)
    for failure in result["failures"]:
        print("  FAIL  " + failure)
    print("RESULT:", "PASS" if result["ok"] else f"FAIL ({len(result['failures'])} problems)")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
