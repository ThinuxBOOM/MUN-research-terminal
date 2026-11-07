"""Discover documents for a topic via the UN Digital Library, then fetch and ingest.

The plan's fetcher is meant to build the real list rather than trust a hand-written one:
this queries the Digital Library's MARCXML search, extracts S/PV meeting records and
SC/ press releases, downloads them, and keeps only files that actually mention the topic.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.parse
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect  # noqa: E402
from app.ingest import clean  # noqa: E402
from app.ingest.pipeline import ingest_file, seed_reference_data  # noqa: E402
from app.settings import CORPUS_RAW  # noqa: E402

UA = "Mozilla/5.0 (compatible; MUNResearchStation/1.0; local research tool)"
SEARCH = "https://digitallibrary.un.org/search"


def search_symbols(topic: str, rows: int = 100) -> tuple[list[str], list[str]]:
    params = {"ln": "en", "p": topic, "of": "xm", "rg": rows}
    resp = httpx.get(SEARCH, params=params, timeout=60, headers={"User-Agent": UA})
    resp.raise_for_status()
    xml = resp.text
    pvs = sorted({f"S/PV.{n}" for n in re.findall(r"S/PV\.(\d{1,5})", xml)}, key=lambda s: int(s.split(".")[1]))
    scs = sorted({f"SC/{n}" for n in re.findall(r"SC/(\d{4,5})", xml)}, key=lambda s: int(s.split("/")[1]))
    return pvs, scs


def symbol_url(symbol: str) -> str:
    return ("https://documents.un.org/api/symbol/access?s="
            + urllib.parse.quote(symbol) + "&l=en&t=pdf")


def download(symbol: str, delay: float = 1.2) -> Path | None:
    CORPUS_RAW.mkdir(parents=True, exist_ok=True)
    target = CORPUS_RAW / (symbol.replace("/", "_") + ".pdf")
    if target.exists() and target.stat().st_size > 1000:
        return target
    time.sleep(delay)
    try:
        resp = httpx.get(symbol_url(symbol), headers={"User-Agent": UA},
                         timeout=90, follow_redirects=True)
        if resp.status_code != 200 or b"%PDF" not in resp.content[:1024]:
            return None
        target.write_bytes(resp.content)
        return target
    except Exception:  # noqa: BLE001
        return None


def mentions(path: Path, words: list[str]) -> bool:
    try:
        text = " ".join(" ".join(page) for page in clean.extract_pages(path))
    except Exception:  # noqa: BLE001
        return False
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and ingest documents for a topic.")
    parser.add_argument("topic", help="topic to search, e.g. Haiti")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    print(f"Searching the UN Digital Library for '{args.topic}' …")
    pvs, scs = search_symbols(args.topic)
    print(f"  found {len(pvs)} S/PV meeting records and {len(scs)} press releases")
    candidates = pvs[: args.limit]
    print("  fetching: " + ", ".join(candidates) if candidates else "  nothing to fetch")

    conn = connect()
    seed_reference_data(conn)
    kept = skipped = 0
    for symbol in candidates:
        path = download(symbol)
        if not path:
            print(f"  [--] {symbol}: download blocked; add it to corpus/inbox by hand")
            continue
        if not mentions(path, [args.topic]):
            skipped += 1
            print(f"  [--] {symbol}: does not mention {args.topic}, skipped")
            continue
        if args.no_ingest:
            kept += 1
            continue
        result = ingest_file(conn, path)
        if result["status"] == "ingested":
            kept += 1
            print(f"  [ok] {symbol}: {result['chunks']} chunks, {result['links']} links, "
                  f"topics {result['topics']}")
        else:
            print(f"  [--] {symbol}: {result['message']}")
    conn.close()
    print(f"\n{kept} documents kept for '{args.topic}', {skipped} skipped as off-topic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
