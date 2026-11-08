"""Charter and treaty parser: one article per chunk (plan 6.2)."""
from __future__ import annotations

import re

from ..chunker import make_chunk, split_long

ART_RE = re.compile(r"^Article\s+([IVXLC]+|\d{1,3}[A-Za-z]?)\b[.:]?\s*(.*)$", re.I)
CHAPTER_RE = re.compile(r"^Chapter\s+([IVXLC]+)\b", re.I)


def parse(paragraphs: list[str], meta: dict) -> list[dict]:
    chunks: list[dict] = []
    chapter = ""
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        label = f"Art. {current['number']}" if current.get("number") else "Preamble"
        for piece in split_long(current["text"]):
            chunks.append(make_chunk("article", label, piece, date=meta.get("date"),
                                     section=current.get("chapter") or None))
        current = None

    for raw in paragraphs:
        text = raw.strip()
        if not text:
            continue
        chapter_match = CHAPTER_RE.match(text)
        if chapter_match and len(text) < 120:
            flush()
            chapter = f"Chapter {chapter_match.group(1).upper()}"
            continue
        match = ART_RE.match(text)
        if match:
            flush()
            current = {
                "number": match.group(1),
                "chapter": chapter,
                "text": match.group(2).strip(),
            }
            continue
        if current is None:
            current = {"number": None, "chapter": chapter, "text": text}
        else:
            current["text"] = f"{current['text']} {text}"
    flush()

    if not chunks:
        return [make_chunk("section", f"section {i + 1}", t, date=meta.get("date"))
                for i, t in enumerate(paragraphs) if t.strip()]
    return chunks
