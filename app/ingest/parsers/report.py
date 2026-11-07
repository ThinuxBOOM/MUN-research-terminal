"""SG report / ICJ opinion parser: numbered paragraph or short section per chunk."""
from __future__ import annotations

import re

from ..chunker import make_chunk, split_long

NUM_RE = re.compile(r"^(\d{1,3})[.)]\s+(.*)$")
SKIP = (
    r"^United Nations$", r"^Security Council$", r"^General Assembly$",
    r"^Distr\.", r"^\d{2}-\d{5}", r"^[SA]/\d{2,4}/", r"^\d{1,2} \w+ \d{4}$",
)


def _skip(text: str) -> bool:
    return any(re.match(p, text.strip(), re.I) for p in SKIP)


def parse(paragraphs: list[str], meta: dict) -> list[dict]:
    chunks: list[dict] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        for piece in split_long(current["text"]):
            chunks.append(make_chunk("paragraph", current["label"], piece,
                                     date=meta.get("date")))
        current = None

    for raw in paragraphs:
        text = raw.strip()
        if not text or _skip(text):
            continue
        match = NUM_RE.match(text)
        if match:
            flush()
            current = {"label": f"para {match.group(1)}", "text": match.group(2)}
        elif current:
            current["text"] += " " + text
        else:
            current = {"label": "section", "text": text}
    flush()
    return chunks or [
        make_chunk("paragraph", f"para {i + 1}", t, date=meta.get("date"))
        for i, t in enumerate(paragraphs) if t.strip()
    ]
