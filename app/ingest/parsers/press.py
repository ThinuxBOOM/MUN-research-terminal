"""Press release (SC/xxxx) parser: paragraph groups plus the vote summary."""
from __future__ import annotations

import re

from ..chunker import make_chunk, merge_until

SKIP = (
    r"^Security Council$", r"^\d{1,3}(st|nd|rd|th) Meeting", r"^SC/\d+$",
    r"^\d{1,2} \w+ \d{4}$", r"^Department of", r"^For immediate release",
    r"^Press Release$", r"^[A-Z]{2}/\d+$",
)

VOTE_LINE = re.compile(
    r"(adopted|approved)[^.]{0,80}?(\d{1,3})\s+votes?\s+to\s+(\d{1,3})"
    r"(?:,\s*with\s*(\d{1,3})\s+abstentions?)?",
    re.I,
)
VOTE_LINE_2 = re.compile(
    r"(\d{1,3})\s+votes?\s+in\s+favour[^.]{0,40}?(\d{1,3})\s+against"
    r"(?:[^.]{0,40}?(\d{1,3})\s+abstentions?)?",
    re.I,
)


def _skip(text: str) -> bool:
    return any(re.match(p, text.strip(), re.I) for p in SKIP)


def extract_vote(text: str) -> dict | None:
    """Return {'in_favour': n, 'against': n, 'abstentions': n} if stated."""
    blob = text.replace("\n", " ")
    match = VOTE_LINE_2.search(blob) or VOTE_LINE.search(blob)
    if not match:
        return None
    groups = [g for g in match.groups() if g is not None]
    if len(groups) >= 2:
        return {
            "in_favour": int(groups[-3]) if len(groups) >= 3 else int(groups[0]),
            "against": int(groups[-2]) if len(groups) >= 2 else 0,
            "abstentions": int(groups[-1]) if len(groups) >= 3 else 0,
        }
    return None


def parse(paragraphs: list[str], meta: dict) -> list[dict]:
    body = [p for p in paragraphs if not _skip(p)]
    # The headline and dateline are the first one or two paragraphs.
    if body:
        meta.setdefault("title", body[0][:200])
    grouped = merge_until(body[1:] if len(body) > 1 else body, 260)
    return [
        make_chunk("paragraph", f"para {i + 1}", text, date=meta.get("date"))
        for i, text in enumerate(grouped)
    ]
