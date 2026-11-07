"""Retrieval orchestration: route, hybrid search, rerank, expand, pack (plan 7)."""
from __future__ import annotations

import time

from ..llm.client import LLMClient
from ..settings import config
from . import fusion, graph, pack as packmod, rerank, router, search


def retrieve(conn, question: str, conference: dict | None = None,
             extra_filters: dict | None = None) -> dict:
    started = time.perf_counter()
    routed = router.route(conn, question, conference)
    filters = dict(routed["filters"])
    for key, value in (extra_filters or {}).items():
        if value:
            filters[key] = value

    client = LLMClient()
    query_vector = client.embed([question])[0]
    allowed = search.allowed_chunk_ids(conn, filters)

    exact = router.exact_ids(conn, routed, filters)
    fts_rows = search.fts_search(conn, question, allowed=allowed)
    vec_rows = search.vector_search(conn, query_vector, allowed=allowed)
    fused = fusion.rrf([exact, fts_rows, vec_rows])
    candidate_ids = [chunk_id for chunk_id, _ in fused[:40]]

    candidates = search.load_chunks(conn, candidate_ids)
    # If filters were too tight, fall back to unfiltered vector candidates so the
    # user still sees the closest passages instead of a blank panel.
    widened = False
    if not candidates:
        allowed = None
        fts_rows = search.fts_search(conn, question)
        vec_rows = search.vector_search(conn, query_vector)
        fused = fusion.rrf([exact, fts_rows, vec_rows])
        candidates = search.load_chunks(conn, [cid for cid, _ in fused[:40]])
        widened = True

    vectors = packmod.embeddings_for(conn, candidates)
    top_k = int(config()["retrieval"]["rerank_top_k"])
    pool = max(top_k * 4, 30)
    ranked_pool = rerank.rank(question, query_vector, candidates, top_k=pool, embeddings=vectors)
    # Drop passages far below the best hit so weak lexical matches do not pad the pack.
    if ranked_pool:
        top_score = ranked_pool[0]["score"]
        floor = top_score * 0.5
        trimmed = [item for item in ranked_pool if item["score"] >= floor]
        ranked_pool = trimmed or ranked_pool[:1]
    # Diversify BEFORE trimming: one long resolution must not crowd out the others,
    # so a linked resolution can still reach the pack for a related question.
    per_doc: dict = {}
    diverse: list[dict] = []
    for item in ranked_pool:
        doc_key = item.get("doc_id")
        per_doc[doc_key] = per_doc.get(doc_key, 0) + 1
        if per_doc[doc_key] <= 3:
            diverse.append(item)
    ranked = (diverse or ranked_pool)[:top_k]
    expanded = graph.expand(conn, ranked)
    combined = fusion.dedupe(ranked + expanded, key="id")
    combined = fusion.dedupe_text(combined)
    items, text = packmod.build_pack(combined)

    best = max((item["score"] for item in items if item.get("score") is not None), default=0.0)
    threshold = float(config()["retrieval"]["min_rerank_score"])
    low_evidence = (not items) or (best < threshold and not routed.get("exact"))
    elapsed = round((time.perf_counter() - started) * 1000)

    return {
        "question": question,
        "routed": routed,
        "filters": filters,
        "pack": items,
        "pack_text": text,
        "best_score": round(best, 4),
        "threshold": threshold,
        "low_evidence": low_evidence,
        "widened": widened,
        "retrieval_ms": elapsed,
        "budget": packmod.budget_report(items),
    }
