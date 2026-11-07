"""Rebuild every embedding, e.g. after changing the embedding model (plan 3)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect  # noqa: E402
from app.ingest.pipeline import backfill_embeddings  # noqa: E402
from app.settings import config  # noqa: E402


def main() -> int:
    conn = connect()
    if "--force" in sys.argv:
        conn.execute("DELETE FROM chunk_vec")
        conn.commit()
        print("Cleared existing vectors.")
    print(f"Embedding with {config()['llm']['embed_model']} on CPU (may take a while) …")
    count = backfill_embeddings(conn)
    conn.close()
    print(f"Done. {count} chunks embedded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
