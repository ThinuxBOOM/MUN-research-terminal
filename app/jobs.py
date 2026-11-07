"""Tiny background job system: a thread per job, progress in the jobs table."""
from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime
from typing import Callable

from .db import connect


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create(conn, kind: str, payload: dict | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO jobs(kind, status, progress, message, payload, created_at) "
        "VALUES (?, 'queued', 0, 'Waiting to start', ?, ?)",
        (kind, json.dumps(payload or {}), _now()),
    )
    conn.commit()
    return int(cursor.lastrowid)


def update(conn, job_id: int, **fields) -> None:
    if not fields:
        return
    allowed = {k: v for k, v in fields.items() if k in ("status", "progress", "message", "payload")}
    if not allowed:
        return
    assignments = ", ".join(f"{key} = ?" for key in allowed)
    conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*allowed.values(), job_id))
    conn.commit()


def run_async(job_id: int, target: Callable, *args, **kwargs) -> None:
    def wrapper() -> None:
        conn = connect()
        try:
            update(conn, job_id, status="running", progress=0.01, message="Starting")
            target(conn, job_id, *args, **kwargs)
            update(conn, job_id, status="done", progress=1.0, message="Finished")
        except Exception as exc:  # noqa: BLE001 - the user needs a plain-English reason
            friendly = getattr(exc, "friendly", None) or str(exc)
            update(conn, job_id, status="failed", message=f"{friendly}")
            log = connect()
            log.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (f"job.{job_id}.error", traceback.format_exc()[-4000:]))
            log.commit()
            log.close()
        finally:
            conn.close()

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()


def recent(conn, limit: int = 20) -> list[dict]:
    return [dict(row) for row in conn.execute(
        "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def get(conn, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None
