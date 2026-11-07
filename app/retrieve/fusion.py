"""Reciprocal Rank Fusion for merging ranked lists (plan 7.3)."""
from __future__ import annotations


def rrf(ranked_lists: list[list], k: int = 60) -> list[tuple[int, float]]:
    """Each input is a list of (id, score) or plain ids. Higher fused score wins."""
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked or [], start=1):
            item_id = item[0] if isinstance(item, (tuple, list)) else item
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: -pair[1])


def dedupe(items: list[dict], key: str = "id") -> list[dict]:
    seen: set = set()
    out: list[dict] = []
    for item in items:
        marker = item.get(key)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def dedupe_text(items: list[dict], threshold: float = 0.9) -> list[dict]:
    """Drop near-identical passages using word-shingle overlap."""
    def shingles(text: str) -> set[str]:
        words = text.lower().split()
        return {" ".join(words[i:i + 8]) for i in range(max(1, len(words) - 7))}

    kept: list[dict] = []
    seen: list[set] = []
    for item in items:
        current = shingles(item.get("text", ""))
        if any(current and prev and len(current & prev) / max(len(current | prev), 1) > threshold
               for prev in seen):
            continue
        seen.append(current)
        kept.append(item)
    return kept
