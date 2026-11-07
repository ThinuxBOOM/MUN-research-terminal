"""PDF text extraction and cleaning (plan 6.1).

PyMuPDF blocks are used instead of raw lines so two-column UN documents keep
their reading order. Running headers, page numbers and repeated symbol stamps
are dropped; hyphenated line breaks are repaired.
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from ..textutil import normalize_ws


def _is_page_number(text: str) -> bool:
    return bool(re.fullmatch(r"\d{1,3}", text.strip()))


def _is_stamp(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 60:
        return False
    return bool(re.fullmatch(r"(Page\s+)?\d{1,3}(\s+of\s+\d{1,3})?", stripped, re.I))


def extract_pages(path: str | Path) -> list[list[str]]:
    """Return paragraphs grouped by page."""
    pages: list[list[str]] = []
    with pymupdf.open(str(path)) as doc:
        for page in doc:
            blocks = page.get_text("blocks", sort=True)
            paragraphs: list[str] = []
            for block in blocks:
                text = block[4] if len(block) > 4 else ""
                text = normalize_ws(text)
                if not text or _is_page_number(text) or _is_stamp(text):
                    continue
                paragraphs.append(text)
            pages.append(paragraphs)
    return pages


def _merge_blocks(paragraphs: list[str]) -> list[str]:
    """Join blocks that are clearly one paragraph split by layout."""
    merged: list[str] = []
    for text in paragraphs:
        if merged:
            prev = merged[-1]
            continues = (
                not re.search(r"[.:;!?\"')\]]$", prev)
                and (text[:1].islower() or text[:1] in ",;")
                and len(prev) < 700
            )
            if continues:
                merged[-1] = f"{prev} {text}"
                continue
        merged.append(text)
    return merged


def clean_pages(pages: list[list[str]]) -> tuple[list[str], dict]:
    """Remove repeated headers/footers and return (paragraphs, metrics)."""
    if not pages:
        return [], {"pages": 0, "chars": 0, "chars_per_page": 0}
    counts: dict[str, int] = {}
    for page in pages:
        for text in set(page):
            if len(text) < 80:
                counts[text] = counts.get(text, 0) + 1
    threshold = max(3, int(len(pages) * 0.5))
    repeated = {text for text, n in counts.items() if n >= threshold}

    paragraphs: list[str] = []
    for page in pages:
        kept = [t for t in page if t not in repeated]
        paragraphs.extend(_merge_blocks(kept))

    # Repair hyphenated line breaks inside a paragraph.
    fixed: list[str] = []
    for text in paragraphs:
        text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
        text = re.sub(r"\s*\n\s*", " ", text)
        text = normalize_ws(text)
        if text:
            fixed.append(text)

    chars = sum(len(t) for t in fixed)
    total_pages = len(pages)
    return fixed, {
        "pages": total_pages,
        "chars": chars,
        "chars_per_page": round(chars / max(total_pages, 1)),
        "repeated_lines": len(repeated),
    }


def parse_quality(metrics: dict) -> float:
    """0..1 heuristic. Scanned pages produce very few characters."""
    cpp = metrics.get("chars_per_page", 0)
    if cpp >= 1200:
        return 0.95
    if cpp >= 600:
        return 0.85
    if cpp >= 250:
        return 0.6
    if cpp >= 80:
        return 0.3
    return 0.1


def extract_text_file(path: str | Path) -> tuple[list[str], dict]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    paragraphs = [normalize_ws(p) for p in re.split(r"\n\s*\n", text) if p.strip()]
    chars = sum(len(p) for p in paragraphs)
    return paragraphs, {"pages": 1, "chars": chars, "chars_per_page": chars}
