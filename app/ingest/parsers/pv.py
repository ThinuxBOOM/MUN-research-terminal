"""S/PV meeting record parser: one speaker intervention per chunk (plan 6.2).

PyMuPDF merges neighbouring blocks in these records, so a speaker line can sit in the
middle of a paragraph. The parser therefore scans the whole record for speaker markers
instead of assuming each intervention starts a new line.
"""
from __future__ import annotations

import re

from ..chunker import make_chunk, split_long
from .. import countries

SPEAKER_RE = re.compile(
    r"(?P<title>The President|The Temporary President|The Acting President|The Chairman|"
    r"The Chair|Mr\.|Ms\.|Mrs\.|Sir)\s*"
    r"(?P<name>[^:()]{0,70}?)\s*"
    r"(?:\((?P<country>[^)]{2,60})\))?\s*:",
)
HEADER_END = re.compile(r"The meeting was called to order|^Agenda$", re.I)
SKIP_COUNTRY = re.compile(r"^(spoke|interpretation|via|videoconference|president)", re.I)


def _country(value: str | None) -> str | None:
    if not value or SKIP_COUNTRY.match(value.strip()):
        return None
    return countries.lookup(value)


def parse(paragraphs: list[str], meta: dict) -> list[dict]:
    text = " ".join(p.strip() for p in paragraphs if p.strip())
    matches = list(SPEAKER_RE.finditer(text))
    if not matches:
        return []

    # Skip the roster at the top: its entries are dot-leader lines such as
    # "President: Mrs. X ............ (Country)". The President's actual opening
    # statement comes after them and must be kept (it often reads out vote results).
    segments: list[tuple[re.Match, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        if not body or re.search(r"\.{4,}", body[:200]):
            continue
        segments.append((match, body))

    chunks: list[dict] = []
    for match, body in segments:
        name = (match.group("title") + " " + match.group("name")).strip(" .")
        country_name = match.group("country")
        iso3 = _country(country_name)
        label = name or (country_name or "Speaker")
        if country_name and not SKIP_COUNTRY.match(country_name):
            label = f"{label} ({country_name})"
        for part, piece in enumerate(split_long(body, 400)):
            suffix = "" if part == 0 else f" (cont. {part + 1})"
            chunks.append(make_chunk(
                "intervention", label + suffix, piece,
                speaker_name=name or None,
                speaker_country=iso3,
                meeting_no=meta.get("meeting_no"),
                date=meta.get("date"),
            ))
    return chunks
