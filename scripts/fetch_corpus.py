"""Polite UN document fetcher driven by corpus/manifests/*.yaml (plan 6.7)."""
from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect  # noqa: E402
from app.ingest.pipeline import ingest_file, seed_reference_data  # noqa: E402
from app.settings import CORPUS_RAW, MANIFEST_DIR  # noqa: E402

UA = "Mozilla/5.0 (compatible; MUNResearchStation/1.0; local research tool)"


def symbol_url(symbol: str) -> str:
    return ("https://documents.un.org/api/symbol/access?s="
            + urllib.parse.quote(symbol) + "&l=en&t=pdf")


def load_manifest(name: str) -> list[dict]:
    path = MANIFEST_DIR / f"{name}.yaml"
    if not path.exists():
        print(f"[!] No manifest named {name}.yaml in {MANIFEST_DIR}")
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = []
    for item in data.get("documents", []):
        if isinstance(item, str):
            entries.append({"symbol": item})
        elif isinstance(item, dict) and item.get("symbol"):
            entries.append(item)
    return entries


def filename_for(symbol: str) -> Path:
    safe = symbol.replace("/", "_").replace(" ", "")
    return CORPUS_RAW / f"{safe}.pdf"


def fetch(entry: dict, delay: float = 1.2) -> tuple[str, Path | None]:
    symbol = entry["symbol"]
    target = filename_for(symbol)
    if target.exists() and target.stat().st_size > 1000:
        return "cached", target
    url = entry.get("url") or symbol_url(symbol)
    try:
        time.sleep(delay)
        with httpx.stream("GET", url, headers={"User-Agent": UA},
                          timeout=60, follow_redirects=True) as resp:
            if resp.status_code != 200:
                return f"http {resp.status_code}", None
            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type and "octet-stream" not in content_type:
                return "not a pdf (open the UN Digital Library and download manually)", None
            with target.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        if target.stat().st_size < 1000:
            target.unlink(missing_ok=True)
            return "empty file", None
        return "downloaded", target
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}", None


def main() -> int:
    parser = argparse.ArgumentParser(description="Download UN documents listed in a manifest.")
    parser.add_argument("packs", nargs="*", default=["core", "haiti"],
                        help="manifest names (default: core haiti)")
    parser.add_argument("--no-ingest", action="store_true", help="download only")
    args = parser.parse_args()

    CORPUS_RAW.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    downloaded = 0
    for pack in args.packs or ["core", "haiti"]:
        entries = load_manifest(pack)
        print(f"\n=== Pack: {pack} ({len(entries)} documents) ===")
        for entry in entries:
            status, path = fetch(entry)
            symbol = entry["symbol"]
            if status in ("downloaded", "cached"):
                downloaded += 1
                print(f"  [ok] {symbol} ({status})")
            else:
                missing.append(f"{symbol}  ({status})")
                print(f"  [--] {symbol}: {status}")

    if missing:
        print("\nThese still need to be downloaded by hand into corpus/inbox:")
        for item in missing:
            print("  - " + item)
        print("Search the UN Digital Library: https://digitallibrary.un.org")

    if not args.no_ingest:
        conn = connect()
        seed_reference_data(conn)
        print("\nIngesting corpus/raw and corpus/inbox …")
        from app.ingest.pipeline import ingest_folder
        from app.settings import CORPUS_INBOX

        for folder in (CORPUS_RAW, CORPUS_INBOX):
            for result in ingest_folder(conn, folder):
                state = result.get("status")
                if state == "ingested":
                    print(f"  [ok] {result.get('symbol')}: {result.get('chunks')} chunks, "
                          f"{result.get('links')} links, quality {result.get('quality')}")
                elif state == "skipped":
                    print(f"  [--] {result.get('symbol') or result.get('file')}: {result['message']}")
                else:
                    print(f"  [!!] {result.get('file', '')}: {result.get('message')}")
        conn.close()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
