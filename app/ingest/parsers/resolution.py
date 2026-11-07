"""Resolution parser: one preambular or operative paragraph per chunk (plan 6.2)."""
from __future__ import annotations

import re

from ..chunker import make_chunk, split_long

OP_RE = re.compile(r"^\(?(\d{1,2})[.)]\s+")
SUB_RE = re.compile(r"^\(([a-z])\)\s+")
PP_VERBS = (
    "recalling", "reaffirming", "noting", "welcoming", "deeply", "expressing", "emphasizing",
    "emphasising", "recognizing", "recognising", "bearing", "mindful", "concerned", "alarmed",
    "stressing", "encouraged", "acknowledging", "considering", "guided", "having", "taking",
    "reiterating", "underlining", "observing", "convinced", "determined", "gravely",
)
HEADER_STOP = re.compile(
    r"^(the security council|the general assembly|the economic and social council)\s*,?\s*$",
    re.I,
)


def _is_header(text: str) -> bool:
    if len(text) <= 4:
        return True
    patterns = (
        r"^United Nations$", r"^(Security Council|General Assembly)$",
        r"^Distr\.", r"^Resolution \d", r"^Adopted by", r"^\d{1,2} \w+ \d{4}$",
        r"^\w+ \d{1,2},? \d{4}$", r"^[SA]/RES/", r"^S/PV\.", r"^\d{2}-\d{5}",
    )
    return any(re.match(p, text, re.I) for p in patterns)


def parse(paragraphs: list[str], meta: dict) -> list[dict]:
    start = 0
    for index, text in enumerate(paragraphs[:40]):
        if HEADER_STOP.match(text.strip()):
            start = index + 1
            break
    body = paragraphs[start:]

    chunks: list[dict] = []
    pp_count = 0
    in_ops = False
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        for piece in split_long(current["text"]):
            chunks.append(make_chunk(current["kind"], current["label"], piece,
                                     date=meta.get("date"), meeting_no=meta.get("meeting_no")))
        current = None

    for text in body:
        stripped = text.strip()
        if not stripped or _is_header(stripped):
            continue
        op_match = OP_RE.match(stripped)
        if op_match and not SUB_RE.match(stripped):
            flush()
            in_ops = True
            number = op_match.group(1)
            current = {
                "kind": "operative",
                "label": f"OP {number}",
                "text": OP_RE.sub("", stripped),
            }
            continue
        if SUB_RE.match(stripped) and in_ops:
            if current:
                current["text"] += " " + stripped
            else:
                current = {"kind": "operative", "label": "OP", "text": stripped}
            continue
        if not in_ops:
            low = stripped.lower()
            looks_like_pp = low.startswith(PP_VERBS) or low.startswith("deeply")
            if current and not looks_like_pp and not current["text"].endswith((".", ":")):
                current["text"] += " " + stripped
                continue
            flush()
            pp_count += 1
            current = {"kind": "preambular", "label": f"PP {pp_count}", "text": stripped}
        else:
            if current:
                current["text"] += " " + stripped
            else:
                current = {"kind": "operative", "label": "OP", "text": stripped}
    flush()

    if not any(c["kind"] == "operative" for c in chunks):
        # Fallback: unnumbered resolution text - keep paragraph chunks.
        return [
            make_chunk("paragraph", f"para {i + 1}", text, date=meta.get("date"))
            for i, text in enumerate(t for t in body if not _is_header(t))
        ]
    return chunks
