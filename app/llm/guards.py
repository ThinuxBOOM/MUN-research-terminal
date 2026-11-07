"""Citation and number guardrails (plan section 8).

The model never supplies a quote. It writes [S#] markers; this module checks
them, expands them from the database-backed pack, and flags sentences whose
numbers cannot be found in the evidence.
"""
from __future__ import annotations

import re

from ..textutil import sentences

MARKER_RE = re.compile(r"\[(S\d+)\]")
RES_NUM_RE = re.compile(r"\bresolution\s+(\d{1,4})\b", re.I)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
VOTE_RE = re.compile(
    r"\b(\d{1,3})\s+(?:votes?|in favour|against|abstentions?|abstained)", re.I)
SYMBOL_RE = re.compile(r"\b([SA])/RES/(\d{1,4})(?:\s*\(([IVXLC]+|\d{4})\))?", re.I)


def valid_markers(text: str, pack_ids: set[str]) -> tuple[list[str], list[str]]:
    used = MARKER_RE.findall(text or "")
    bad = [m for m in used if m not in pack_ids]
    return sorted(set(used)), sorted(set(bad))


def expand(text: str, pack: list[dict]) -> str:
    """Replace each [S#] with the full citation, quoting nothing from the model."""
    by_id = {item["id"]: item for item in pack}
    def repl(match: re.Match) -> str:
        item = by_id.get(match.group(1))
        if not item:
            return match.group(0)
        parts = [item.get("symbol") or "source"]
        if item.get("label"):
            parts.append(item["label"])
        if item.get("date"):
            parts.append(item["date"])
        return " [" + " · ".join(parts) + "]"
    return MARKER_RE.sub(repl, text or "")


def _evidence_numbers(pack: list[dict], votes: list[dict] | None) -> set[str]:
    blob = " ".join(
        " ".join(str(item.get(k) or "") for k in ("symbol", "label", "date", "text"))
        for item in pack
    )
    found = set(YEAR_RE.findall(blob))
    found.update(n for n in RES_NUM_RE.findall(blob))
    found.update(VOTE_RE.findall(blob))
    for group in SYMBOL_RE.findall(blob):
        found.add(group[1])
    for row in votes or []:
        found.add(str(row.get("iso3", "")))
    return found


def check_answer(question: str, answer: str, pack: list[dict],
                 votes: list[dict] | None = None) -> dict:
    """Return a report used by the UI; nothing is hidden from the user."""
    pack_ids = {item["id"] for item in pack}
    used, bad = valid_markers(answer, pack_ids)
    flags: list[dict] = []

    if bad:
        flags.append({
            "level": "error",
            "message": "Citations outside the evidence pack: " + ", ".join(bad),
        })

    allowed_numbers = _evidence_numbers(pack, votes)
    for sentence in sentences(answer):
        unsupported = []
        for number in RES_NUM_RE.findall(sentence):
            if number not in allowed_numbers:
                unsupported.append(f"resolution {number}")
        if VOTE_RE.search(sentence):
            for count in VOTE_RE.findall(sentence):
                if count not in allowed_numbers:
                    unsupported.append(f"vote count {count}")
        for year in YEAR_RE.findall(sentence):
            if year not in allowed_numbers:
                unsupported.append(year)
        if unsupported:
            flags.append({
                "level": "warn",
                "message": "Unverified number(s): " + ", ".join(sorted(set(unsupported))),
                "sentence": sentence,
            })

    uncited = [s for s in sentences(answer) if not MARKER_RE.search(s)]
    if answer.strip() and answer.strip() != "NOT ENOUGH EVIDENCE" and len(uncited) > 0:
        flags.append({
            "level": "warn",
            "message": f"{len(uncited)} sentence(s) carry no citation marker.",
            "sentence": uncited[0],
        })

    refused = answer.strip().upper().startswith("NOT ENOUGH EVIDENCE")
    return {
        "markers": used,
        "bad_markers": bad,
        "flags": flags,
        "refused": refused,
        "clean": not bad,
    }


def validate_resolution_refs(text: str, known_symbols: set[str]) -> list[str]:
    """Working-paper validator: every referenced resolution must exist in the library."""
    missing = []
    for organ, number, year in SYMBOL_RE.findall(text or ""):
        candidates = [s for s in known_symbols if f"/{number}" in s]
        if year:
            candidates = [s for s in candidates if f"({year})" in s or f" ({year})" in s]
        if not candidates and not any(f"/{number}" in s for s in known_symbols):
            missing.append(f"{organ}/RES/{number}" + (f" ({year})" if year else ""))
    for number, year in re.findall(r"\bresolution\s+(\d{1,4})\s*(?:\((\d{4})\))?", text or "", re.I):
        if not any(f"/{number}" in s for s in known_symbols):
            missing.append(f"resolution {number}" + (f" ({year})" if year else ""))
    return sorted(set(missing))
