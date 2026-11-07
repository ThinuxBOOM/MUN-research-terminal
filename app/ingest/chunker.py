"""Chunk assembly helpers: token limits and context headers (plan 6.2)."""
from __future__ import annotations

import re

from ..settings import config
from ..textutil import est_tokens

HEADER_MAX = 40


def make_chunk(kind: str, label: str, text: str, **extra) -> dict:
    text = re.sub(r"\s+", " ", text).strip()
    item = {
        "kind": kind,
        "label": (label or "")[:60],
        "text": text,
        "token_count": est_tokens(text),
    }
    item.update({k: v for k, v in extra.items() if v is not None})
    return item


def split_long(text: str, max_tokens: int | None = None) -> list[str]:
    """Split one paragraph on sentence boundaries, never mid-sentence if avoidable."""
    limit = max_tokens or int(config()["ingest"]["chunk_max_tokens"])
    if est_tokens(text) <= limit:
        return [text]
    pieces = re.split(r"(?<=[.;:])\s+(?=[A-Z0-9(\"'])", text)
    out: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip()
        if est_tokens(candidate) > limit and current:
            out.append(current)
            current = piece
        else:
            current = candidate
    if current:
        out.append(current)
    # Anything still oversized is hard-split.
    final: list[str] = []
    for piece in out:
        if est_tokens(piece) <= limit * 1.4:
            final.append(piece)
        else:
            step = int(limit * 4)
            final.extend(piece[i:i + step] for i in range(0, len(piece), step))
    return [p for p in final if p.strip()]


def merge_until(texts: list[str], target: int | None = None) -> list[str]:
    """Group consecutive short paragraphs up to the target size."""
    goal = target or int(config()["ingest"]["chunk_target_tokens"])
    out: list[str] = []
    current = ""
    for text in texts:
        candidate = f"{current}\n{text}".strip()
        if est_tokens(candidate) > goal and current:
            out.append(current)
            current = text
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def context_text(symbol: str, label: str, organ: str, date: str, text: str) -> str:
    """Text actually embedded: a short header plus the clean chunk text."""
    parts = [p for p in (symbol, label, organ, date) if p]
    header = "[" + " | ".join(parts)[:200] + "]"
    return f"{header} {text}"


def rerank_key(chunk: dict) -> str:
    return f"{chunk.get('symbol', '')} {chunk.get('label', '')}"
