"""Reranker: embedding similarity plus lexical support, on CPU, top 30 -> top 8.

A fastembed cross-encoder can be swapped in here (config has no hard dependency);
the interface is identical: rank(query, query_vector, candidates, top_k).
"""
from __future__ import annotations

import re

import numpy as np

from ..settings import config
from ..textutil import content_words

SYMBOL_RE = re.compile(r"\b([SA])/RES/(\d{1,4})\b", re.I)
ARTICLE_RE = re.compile(r"\bArticle\s+(\d{1,3})\b", re.I)


def _cosine(query_vector, text_vector) -> float:
    q = np.asarray(query_vector, dtype=np.float32)
    t = np.asarray(text_vector, dtype=np.float32)
    denom = float(np.linalg.norm(q) * np.linalg.norm(t))
    if denom == 0:
        return 0.0
    return float(np.dot(q, t) / denom)


def lexical_coverage(query: str, text: str) -> float:
    q_terms = set(content_words(query))
    if not q_terms:
        return 0.0
    t_terms = set(content_words(text))
    return len(q_terms & t_terms) / len(q_terms)


def exact_boost(query: str, chunk: dict) -> float:
    boost = 0.0
    symbol = (chunk.get("symbol") or "").upper()
    for organ, number in SYMBOL_RE.findall(query):
        if f"/{number}" in symbol and symbol.startswith(organ.upper()):
            boost = max(boost, 1.0)
    for article in ARTICLE_RE.findall(query):
        if str(chunk.get("label", "")).replace("Art. ", "") == article:
            boost = max(boost, 0.8)
    return boost


def rank(query: str, query_vector, candidates: list[dict], top_k: int | None = None,
         embeddings: dict[int, list[float]] | None = None) -> list[dict]:
    top_k = top_k or int(config()["retrieval"]["rerank_top_k"])
    scored: list[dict] = []
    for chunk in candidates:
        vector = (embeddings or {}).get(chunk["id"])
        similarity = _cosine(query_vector, vector) if vector is not None else 0.0
        coverage = lexical_coverage(query, chunk.get("text", ""))
        boost = exact_boost(query, chunk)
        score = 0.55 * similarity + 0.30 * coverage + 0.15 * boost
        item = dict(chunk)
        item["score"] = round(score, 4)
        item["similarity"] = round(similarity, 4)
        item["coverage"] = round(coverage, 3)
        scored.append(item)
    scored.sort(key=lambda item: -item["score"])
    return scored[:top_k]
