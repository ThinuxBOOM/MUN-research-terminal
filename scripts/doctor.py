"""doctor: check every moving part and print PASS/FAIL with a fix (plan 12)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import connect, table_count  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402
from app.settings import DB_PATH, config  # noqa: E402

results: list[tuple[bool, str, str]] = []


def check(ok: bool, label: str, fix: str = "", detail: str = "") -> None:
    results.append((ok, label + (f" — {detail}" if detail else ""), fix))


def main() -> int:
    print("MUN Research Station - doctor\n" + "=" * 40)
    check(sys.version_info >= (3, 11), "Python version",
          "Install Python 3.11 or newer from python.org and tick 'Add to PATH'.",
          f"{sys.version.split()[0]}")

    for module, label, fix in [
        ("fastapi", "FastAPI", "Run install.bat to install requirements."),
        ("uvicorn", "Uvicorn", "Run install.bat."),
        ("jinja2", "Jinja2", "Run install.bat."),
        ("pymupdf", "PyMuPDF", "Run install.bat."),
        ("numpy", "numpy", "Run install.bat."),
        ("docx", "python-docx", "Run install.bat."),
    ]:
        try:
            __import__(module)
            check(True, f"Package {label}")
        except Exception:
            check(False, f"Package {label}", fix)

    cfg = config()["llm"]
    client = LLMClient()
    health = client.health()
    check(health["ok"], "Ollama reachable",
          "Open the Ollama app, or run 'ollama serve' in a terminal.", health.get("endpoint", ""))
    if health["ok"]:
        model = cfg["model"]
        check(health["has_model"], f"Model {model} installed",
              f"Run: ollama pull qwen3:8b   then: ollama create {model} -f Modelfile")
        context = client.context_length()
        check(context >= 8192, "Context length applied",
              "Recreate the model: ollama create qwen3-mun -f Modelfile", f"num_ctx={context}")
        check(health["has_embed"], f"Embedding model {cfg['embed_model']} installed",
              f"Run: ollama pull {cfg['embed_model']}")
    else:
        check(False, "Model check skipped", "Start Ollama first.")
        check(False, "Context check skipped", "Start Ollama first.")
        check(False, "Embedding model check skipped", "Start Ollama first.")

    exists = DB_PATH.exists()
    check(exists, "Database file", "Run install.bat, or start the app once.", str(DB_PATH))
    if exists:
        try:
            conn = connect()
            docs = table_count(conn, "documents")
            chunks = table_count(conn, "chunks")
            vectors = table_count(conn, "chunk_vec")
            missing = conn.execute(
                "SELECT COUNT(*) AS n FROM chunks c LEFT JOIN chunk_vec v ON v.chunk_id=c.id "
                "WHERE v.chunk_id IS NULL").fetchone()["n"]
            conn.close()
            check(True, "Database readable", "", f"{docs} documents, {chunks} chunks")
            check(missing == 0, "All chunks embedded",
                  "Run: python -m app.ingest.pipeline  (it embeds missing chunks)", f"{missing} missing")
            check(docs > 0, "Library has documents",
                  "Run fetch.bat while online, then start the app.", f"{vectors} vectors")
        except Exception as exc:
            check(False, "Database readable", "Delete data/mun.db and restart; it is rebuilt.",
                  str(exc))

    free_gb = shutil.disk_usage(str(ROOT)).free / (1024 ** 3)
    check(free_gb > 2, "Disk space", "Free some space; models and the library need room.",
          f"{free_gb:.1f} GB free on the drive")

    print()
    failures = 0
    for ok, label, fix in results:
        print(("PASS  " if ok else "FAIL  ") + label)
        if not ok and fix:
            print("      fix: " + fix)
            failures += 1
    print("\n" + "=" * 40)
    if failures:
        print(f"{failures} check(s) need attention. Fix the items marked FAIL above.")
        return 1
    print("Everything looks good. Double-click start.bat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
