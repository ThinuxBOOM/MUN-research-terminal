"""Evidence pack assembly: short IDs, token budget, no duplicates (plan 7.6)."""
from __future__ import annotations

from ..settings import config
from ..textutil import clamp_tokens, est_tokens
from ..vectorindex import get_embedding


def label_for(chunk: dict) -> str:
    label = chunk.get("label") or ""
    if chunk.get("speaker_name") and not label:
        label = chunk["speaker_name"]
    return label


def build_pack(chunks: list[dict], budget: int | None = None) -> tuple[list[dict], str]:
    budget = budget or int(config()["retrieval"]["pack_token_budget"])
    items: list[dict] = []
    lines: list[str] = []
    used = 0
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        symbol = chunk.get("symbol") or "unknown document"
        label = label_for(chunk) or "text"
        date = chunk.get("date") or ""
        header = f"[S{len(items) + 1}] {symbol} | {label}" + (f" | {date}" if date else "")
        remaining = budget - used - est_tokens(header) - 8
        if remaining < 40:
            break
        body = clamp_tokens(text, remaining)
        cost = est_tokens(header) + est_tokens(body)
        used += cost
        item = {
            "id": f"S{len(items) + 1}",
            "chunk_id": chunk["id"],
            "doc_id": chunk.get("doc_id"),
            "symbol": symbol,
            "label": label,
            "date": date,
            "title": chunk.get("title"),
            "doc_type": chunk.get("doc_type"),
            "speaker_country": chunk.get("speaker_country"),
            "meeting_no": chunk.get("meeting_no"),
            "text": body,
            "score": chunk.get("score"),
        }
        items.append(item)
        lines.append(f"{header}\n{body}")
        if used >= budget:
            break
    return items, "\n\n".join(lines)


def pack_text(items: list[dict]) -> str:
    return "\n\n".join(
        f"[{item['id']}] {item['symbol']} | {item['label']}"
        + (f" | {item['date']}" if item.get("date") else "")
        + f"\n{item['text']}" for item in items
    )


def embeddings_for(conn, chunks: list[dict]) -> dict[int, list[float]]:
    out: dict[int, list[float]] = {}
    for chunk in chunks:
        vector = get_embedding(conn, chunk["id"])
        if vector is not None:
            out[chunk["id"]] = vector.tolist()
    return out


def budget_report(items: list[dict], budget: int | None = None) -> dict:
    budget = budget or int(config()["retrieval"]["pack_token_budget"])
    used = sum(est_tokens(i["text"]) + est_tokens(i["symbol"] + i["label"]) for i in items)
    return {"used": used, "budget": budget, "items": len(items),
            "pct": round(100 * used / budget, 1)}
