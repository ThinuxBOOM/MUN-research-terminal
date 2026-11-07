"""Start the app and open the browser (used by start.bat)."""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from app.db import init_db  # noqa: E402
from app.ingest.pipeline import seed_reference_data  # noqa: E402
from app.settings import config  # noqa: E402


def free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def main() -> int:
    cfg = config()["app"]
    print("Preparing the database …")
    conn = init_db()
    seed_reference_data(conn)
    conn.close()

    port = free_port(int(cfg["port"]))
    url = f"http://127.0.0.1:{port}"
    print(f"\nMUN Research Station is starting at {url}")
    print("Keep this window open while you work. Press Ctrl+C to stop.\n")

    def open_later() -> None:
        time.sleep(2.0)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=open_later, daemon=True).start()
    uvicorn.run("app.main:app", host=cfg["host"], port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
