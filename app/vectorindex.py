"""Embedding storage and cosine search.

sqlite-vec is used when its extension can be loaded; otherwise vectors are kept
as float32 BLOBs and scanned with numpy. At library sizes this app targets
(thousands of chunks) the numpy path is a few milliseconds, so behaviour is
identical either way. Only the storage is swapped, never the ranking maths.
"""
from __future__ import annotations

import sqlite3

import numpy as np


def _as_array(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).reshape(dim)


def save_embedding(conn: sqlite3.Connection, chunk_id: int, vector) -> None:
    arr = np.asarray(vector, dtype=np.float32)
    conn.execute(
        "INSERT INTO chunk_vec(chunk_id, dim, vec) VALUES (?, ?, ?) "
        "ON CONFLICT(chunk_id) DO UPDATE SET dim = excluded.dim, vec = excluded.vec",
        (chunk_id, int(arr.shape[0]), arr.tobytes()),
    )


def has_embeddings(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) AS n FROM chunk_vec").fetchone()
    return bool(row and row["n"])


def get_embedding(conn: sqlite3.Connection, chunk_id: int):
    row = conn.execute("SELECT dim, vec FROM chunk_vec WHERE chunk_id = ?", (chunk_id,)).fetchone()
    if not row:
        return None
    return _as_array(row["vec"], row["dim"])


def load_matrix(conn: sqlite3.Connection, allowed: set[int] | None = None):
    """Return (chunk_ids, matrix L2-normalised) for cosine scoring."""
    rows = conn.execute("SELECT chunk_id, dim, vec FROM chunk_vec").fetchall()
    ids: list[int] = []
    vectors: list[np.ndarray] = []
    for row in rows:
        if allowed is not None and row["chunk_id"] not in allowed:
            continue
        ids.append(row["chunk_id"])
        vectors.append(_as_array(row["vec"], row["dim"]))
    if not ids:
        return [], np.zeros((0, 0), dtype=np.float32)
    matrix = np.vstack(vectors)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return ids, matrix / norms


def cosine_search(conn: sqlite3.Connection, query_vector, top_k: int = 30,
                  allowed: set[int] | None = None) -> list[tuple[int, float]]:
    ids, matrix = load_matrix(conn, allowed)
    if not ids:
        return []
    q = np.asarray(query_vector, dtype=np.float32)
    norm = np.linalg.norm(q)
    if norm == 0:
        return []
    q = q / norm
    if matrix.shape[1] != q.shape[0]:
        return []
    scores = matrix @ q
    order = np.argsort(-scores)[:top_k]
    return [(ids[i], float(scores[i])) for i in order]
