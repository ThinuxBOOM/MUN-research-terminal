"""All live modes. Code retrieves and validates; the model only writes text (plan 8, 9)."""
from __future__ import annotations

import re

from ..ingest import votes as votes_mod
from ..llm import guards, prompts
from ..llm.client import LLMClient
from ..retrieve import graph, pack as packmod, search, service
from ..settings import config

REFUSAL = "NOT ENOUGH EVIDENCE"
NOT_FOUND = ("Not found in your library. The closest passages are shown on the left; "
             "add the relevant document to the library before relying on an answer.")


def _evidence_items(pack: list[dict]) -> list[dict]:
    return [{
        "id": item["id"], "symbol": item["symbol"], "label": item["label"],
        "date": item.get("date"), "text": item["text"], "chunk_id": item["chunk_id"],
        "doc_id": item.get("doc_id"), "speaker_country": item.get("speaker_country"),
        "score": item.get("score"),
    } for item in pack]


def _topic_name(conn, topic_id: int | None) -> str:
    if not topic_id:
        return ""
    row = conn.execute("SELECT name FROM topics WHERE id = ?", (topic_id,)).fetchone()
    return row["name"] if row else ""


# --------------------------------------------------------------------- prepare
def prepare(conn, mode: str, payload: dict) -> dict:
    question = (payload.get("question") or "").strip()
    conference = payload.get("conference")
    iso3 = payload.get("country")
    base = {"mode": mode, "question": question, "conference": conference,
            "evidence": [], "votes": [], "meta": {}, "pack": [], "pack_text": "",
            "refusal": None, "retrieval_ms": 0, "budget": {}}

    if mode == "stance":
        return _prepare_stance(conn, base, question, iso3 or
                               (conference or {}).get("my_country"),
                               (conference or {}).get("topic_id"))
    if mode == "connect":
        return _prepare_connect(conn, base, question, payload)

    extra = payload.get("filters") or {}
    result = service.retrieve(conn, question, conference, extra)
    items = result["pack"]
    base.update({
        "evidence": _evidence_items(items),
        "pack": items,
        "pack_text": result["pack_text"],
        "retrieval_ms": result["retrieval_ms"],
        "budget": result["budget"],
        "routed": result["routed"],
        "best_score": result["best_score"],
        "meta": {
            "retrieval_ms": result["retrieval_ms"],
            "best_score": result["best_score"],
            "threshold": result["threshold"],
            "filters": result["filters"],
            "low_evidence": result["low_evidence"],
            "widened": result["widened"],
            "mode": mode,
        },
    })
    routed = result["routed"]
    # Vote and stance questions must not be answered from unrelated passages.
    if re.search(r"\bvote[ds]?\b|\bvoting\b", question, re.I) and not conn.execute(
            "SELECT 1 FROM votes LIMIT 1").fetchone():
        base["meta"]["no_vote_data"] = True
        base["refusal"] = ("No vote data. The votes table is empty, so no vote can be quoted. "
                           "Add votes on the Votes page, or import a UN Digital Library CSV.")
        return base
    if routed["mode"] == "stance" and routed.get("country"):
        has_statements = conn.execute(
            "SELECT 1 FROM chunks WHERE speaker_country = ? LIMIT 1",
            (routed["country"],)).fetchone()
        if not has_statements:
            base["meta"]["no_data"] = True
            base["refusal"] = (f"No data. The library has no statements or votes for "
                               f"{routed['country']} on this agenda.")
            return base
    if result["low_evidence"]:
        base["refusal"] = NOT_FOUND
        return base

    cues = {
        "evidence": prompts.render("evidence", pack="{pack}", question=question),
        "argue": prompts.render("argument", extra=iso3 or (conference or {}).get("my_country") or "my country"),
        "counter": prompts.render("counter", question=question),
        "check": prompts.render("check_clause", question=question),
    }
    template = cues.get(mode, cues["evidence"])
    system = prompts.BASE_RULES
    user = template.replace("{pack}", result["pack_text"]).replace("{question}", question)
    if mode in ("argue", "counter", "check") and "{question}" not in template:
        user = user.replace("{pack}", result["pack_text"])
    base["system"] = system
    base["user"] = user
    base["evidence"] = _evidence_items(items)
    return base


def _prepare_stance(conn, base: dict, question: str, iso3: str | None,
                    topic_id: int | None) -> dict:
    topic_name = _topic_name(conn, topic_id)
    base["meta"].update({"country": iso3, "topic": topic_name})
    if not iso3:
        base["refusal"] = "Pick a country for a stance question, or name one in the question."
        return base

    vote_rows = votes_mod.votes_for_country(conn, iso3, topic_id)
    statements = search.statements_for_country(conn, iso3, topic_id, limit=12)
    if not statements and not vote_rows:
        base["refusal"] = (f"No data. The library holds no statements or votes for "
                           f"{iso3} on this agenda yet.")
        base["meta"]["no_data"] = True
        return base

    chunks = sorted(statements, key=lambda row: (row.get("date") or ""))
    items, pack_text = packmod.build_pack(chunks, budget=int(config()["retrieval"]["pack_token_budget"]) - 400)
    vote_lines = [f"{row['symbol']} ({row['date'] or 'no date'}): {row['vote']}"
                  for row in vote_rows]
    if vote_lines:
        pack_text += "\n\nVOTES (from the votes table, not the model):\n" + "\n".join(vote_lines)
    base.update({
        "pack": items,
        "pack_text": pack_text,
        "evidence": _evidence_items(items),
        "votes": vote_rows,
        "budget": packmod.budget_report(items),
        "system": prompts.BASE_RULES,
        "user": prompts.render(
            "stance", pack=pack_text,
            extra=f"the stance of {iso3} on {topic_name or 'this agenda'}",
            question=f"What is the stance of {iso3} on {topic_name}?"),
    })
    if not items:
        base["refusal"] = (f"No statements found for {iso3}. Votes are shown, but a stance "
                           f"summary needs at least one statement in the library.")
    return base


def _prepare_connect(conn, base: dict, question: str, payload: dict) -> dict:
    target_a = payload.get("doc_a") or ""
    target_b = payload.get("doc_b") or ""
    doc_a = graph.find_doc(conn, target_a)
    doc_b = graph.find_doc(conn, target_b)
    if not doc_a or not doc_b:
        base["refusal"] = "Both documents must exist in the library (use their symbols, e.g. S/RES/2699 (2023))."
        return base
    path = graph.path_between(conn, doc_a["id"], doc_b["id"])
    if path is None:
        base["refusal"] = f"No accepted connection path found between {doc_a['symbol']} and {doc_b['symbol']}."
        base["meta"].update({"doc_a": doc_a["symbol"], "doc_b": doc_b["symbol"]})
        return base

    hops = graph.path_narrative(conn, path)
    chunks: list[dict] = []
    for hop in hops:
        for doc_id in (hop["from"].get("id"), hop["to"].get("id")):
            if not doc_id:
                continue
            row = conn.execute(
                "SELECT c.*, d.symbol, d.title, d.doc_type, d.organ, d.date AS doc_date "
                "FROM chunks c JOIN documents d ON d.id = c.doc_id "
                "WHERE c.doc_id = ? ORDER BY c.ordinal LIMIT 1", (doc_id,)).fetchone()
            if row:
                item = dict(row)
                item["date"] = item.get("date") or item.get("doc_date")
                chunks.append(item)
    items, pack_text = packmod.build_pack(chunks)
    base.update({
        "pack": items, "pack_text": pack_text, "evidence": _evidence_items(items),
        "budget": packmod.budget_report(items),
        "system": prompts.BASE_RULES,
        "user": prompts.render(
            "connect", pack=pack_text,
            question=f"Explain the path from {doc_a['symbol']} to {doc_b['symbol']}."),
        "meta": {"doc_a": doc_a["symbol"], "doc_b": doc_b["symbol"], "path": hops},
    })
    return base


# -------------------------------------------------------------------- generate
def generate(prep: dict, temperature: float | None = None):
    if prep.get("refusal"):
        yield prep["refusal"]
        return
    client = LLMClient()
    temp = temperature if temperature is not None else float(
        config()["llm"]["temperature_evidence"])
    yield from client.stream(prep["system"], prep["user"], temperature=temp)


def finalize(prep: dict, answer: str) -> dict:
    if prep.get("refusal"):
        return {"answer": prep["refusal"], "expanded": prep["refusal"],
                "flags": [], "refused": True, "valid": True}
    report = guards.check_answer(prep.get("question", ""), answer, prep.get("pack", []),
                                 prep.get("votes"))
    expanded = guards.expand(answer, prep.get("pack", []))
    return {
        "answer": answer,
        "expanded": expanded,
        "flags": report["flags"],
        "refused": report["refused"],
        "valid": report["clean"],
        "markers": report["markers"],
    }


def run(conn, mode: str, payload: dict) -> dict:
    prep = prepare(conn, mode, payload)
    answer = "".join(generate(prep))
    result = finalize(prep, answer)
    result["evidence"] = prep.get("evidence", [])
    result["votes"] = prep.get("votes", [])
    result["meta"] = prep.get("meta", {})
    result["pack_text"] = prep.get("pack_text", "")
    result["retrieval_ms"] = prep.get("meta", {}).get("retrieval_ms", 0)
    return result
