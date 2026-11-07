"""Integration tests on real PDFs: ingest, labels, idempotency, retrieval fusion."""
from pathlib import Path

import pytest

from app.db import init_db
from app.ingest.pipeline import ingest_file, seed_reference_data
from app.retrieve import fusion, rerank

PDF = Path(__file__).resolve().parent.parent / "corpus" / "raw" / "S_RES_2699(2023).pdf"


@pytest.fixture()
def conn(tmp_path):
    connection = init_db(tmp_path / "test.db")
    seed_reference_data(connection)
    yield connection
    connection.close()


@pytest.mark.skipif(not PDF.exists(), reason="seed PDF not downloaded")
def test_ingest_real_resolution_is_labeled_and_idempotent(conn):
    first = ingest_file(conn, PDF, embed=False)
    assert first["status"] == "ingested"
    assert first["symbol"] == "S/RES/2699 (2023)"
    assert first["doc_type"] == "resolution"
    labels = [row["label"] for row in conn.execute(
        "SELECT label FROM chunks WHERE doc_id = ? ORDER BY ordinal", (first["doc_id"],))]
    assert "OP 1" in labels and any(label.startswith("PP ") for label in labels)
    texts = [row["text"] for row in conn.execute("SELECT text FROM chunks WHERE doc_id = ?",
                                                (first["doc_id"],))]
    assert any("Multinational Security Support" in text for text in texts)

    second = ingest_file(conn, PDF, embed=False)
    assert second["status"] == "skipped"
    # Reference stubs may be created by link extraction; only one real document exists.
    real = conn.execute("SELECT COUNT(*) AS n FROM documents WHERE status != 'stub'").fetchone()["n"]
    assert real == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM chunks WHERE doc_id = ?",
                        (first["doc_id"],)).fetchone()["n"] == first["chunks"]


def test_rrf_merges_lists_by_rank():
    fused = fusion.rrf([[3, 1], [1, 5]])
    ids = [item[0] for item in fused]
    assert ids[0] == 1
    assert set(ids) == {1, 3, 5}


def test_rerank_prefers_exact_symbol_match():
    query = "What does S/RES/2699 (2023) say about the mission?"
    vector = [1.0, 0.0]
    candidates = [
        {"id": 1, "symbol": "S/RES/2645 (2022)", "label": "OP 4", "text": "Extends BINUH."},
        {"id": 2, "symbol": "S/RES/2699 (2023)", "label": "OP 1",
         "text": "Authorizes the Multinational Security Support mission."},
    ]
    ranked = rerank.rank(query, vector, candidates, top_k=2,
                         embeddings={1: [0.0, 1.0], 2: [0.0, 1.0]})
    assert ranked[0]["id"] == 2


def test_exact_chunk_search_finds_article(tmp_path):
    conn = init_db(tmp_path / "t.db")
    seed_reference_data(conn)
    doc_id = conn.execute(
        "INSERT INTO documents(symbol, title, doc_type, status) VALUES "
        "('A/CONF.39/27', 'VCLT', 'treaty', 'ok')").lastrowid
    conn.execute("INSERT INTO chunks(doc_id, ordinal, kind, label, text, token_count) VALUES "
                 "(?, 1, 'article', 'Art. 51', 'Nothing shall impair self-defence.', 8)",
                 (doc_id,))
    conn.commit()
    from app.retrieve import router, search

    routed = router.route(conn, "What does Article 51 say?")
    ids = router.exact_ids(conn, routed)
    chunks = search.load_chunks(conn, ids)
    assert chunks and chunks[0]["label"] == "Art. 51"
    conn.close()
