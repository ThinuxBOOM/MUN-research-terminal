"""Dossier pipeline: ten sections, each saved as soon as it is finished (plan 10)."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime

from ..ingest import countries, votes as votes_mod
from ..llm import guards, prompts
from ..llm.client import LLMClient, LLMError
from ..modes import service as modes
from ..retrieve import service
from ..settings import config

SECTIONS = [
    ("background", "Agenda background"),
    ("legal", "Legal framework"),
    ("history", "Resolution history"),
    ("profiles", "Country profiles"),
    ("blocs", "Blocs and alliances"),
    ("position", "My country's position"),
    ("counter", "Likely counterarguments"),
    ("speech", "Opening speech"),
    ("working_paper", "Working paper"),
    ("pois", "POIs and follow-ups"),
]
SECTION_TITLES = dict(SECTIONS)


def _save(conn, conference_id: int, section: str, md: str, evidence: list | None = None,
          country: str | None = None, status: str = "ok") -> None:
    conn.execute("DELETE FROM dossier_sections WHERE conference_id = ? AND section = ? "
                 "AND COALESCE(country,'') = COALESCE(?, '')",
                 (conference_id, section, country))
    conn.execute(
        "INSERT INTO dossier_sections(conference_id, section, country, content_md, evidence_json, "
        "status, generated_at) VALUES (?,?,?,?,?,?,?)",
        (conference_id, section, country, md, json.dumps(evidence or []), status,
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()


def _conf(conn, conference_id: int) -> dict:
    row = conn.execute("SELECT * FROM conferences WHERE id = ?", (conference_id,)).fetchone()
    if not row:
        raise RuntimeError("Conference not found.")
    conf = dict(row)
    conf["countries_list"] = json.loads(conf.get("countries") or "[]")
    return conf


def _chat(system: str, user: str, temperature: float | None = None) -> str:
    client = LLMClient()
    try:
        return client.chat(system, user,
                           temperature=temperature if temperature is not None
                           else float(config()["llm"]["temperature_evidence"]))
    except LLMError as exc:
        return f"> Model unavailable: {exc}"


def _topic_docs(conn, topic_id: int | None, limit: int = 40) -> list[dict]:
    if topic_id:
        rows = conn.execute(
            "SELECT d.* FROM documents d JOIN doc_topics dt ON dt.doc_id = d.id "
            "WHERE dt.topic_id = ? AND d.status != 'stub' ORDER BY d.date DESC LIMIT ?",
            (topic_id, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM documents WHERE status != 'stub' "
                            "ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def _evidence_links(items: list[dict]) -> str:
    links = []
    for item in items:
        links.append(f"- **{item['symbol']}** · {item['label']} · {item.get('date') or ''} "
                     f"(chunk {item['chunk_id']})")
    return "\n".join(links)


# ------------------------------------------------------------------ sections
def section_background(conn, conf: dict) -> tuple[str, list, str]:
    result = service.retrieve(conn, conf["agenda"], conf, {"topic_id": conf.get("topic_id")})
    items = result["pack"]
    if not items:
        return "No documents in the library cover this agenda yet.", [], "empty"
    timeline = []
    seen = set()
    for doc in _topic_docs(conn, conf.get("topic_id"), 15):
        if doc["symbol"] in seen:
            continue
        seen.add(doc["symbol"])
        timeline.append(f"| {doc.get('date') or 'n.d.'} | {doc['symbol']} | "
                        f"{doc.get('doc_type')} | {(doc.get('title') or '')[:90]} |")
    system = prompts.BASE_RULES
    user = prompts.render("background", pack=result["pack_text"],
                          question=f"the background of {conf['agenda']}")
    summary = _chat(system, user)
    md = [f"## Agenda background\n\n{summary}\n", "### Timeline of documents in your library\n",
          "| Date | Symbol | Type | Title |", "| --- | --- | --- | --- |", *timeline]
    return "\n".join(md), [i["id"] for i in items], "ok"


def section_legal(conn, conf: dict) -> tuple[str, list, str]:
    rows = conn.execute(
        "SELECT c.*, d.symbol, d.title, d.doc_type, d.date AS doc_date FROM chunks c "
        "JOIN documents d ON d.id = c.doc_id WHERE d.doc_type IN ('charter','treaty') "
        "AND (lower(c.text) LIKE '%chapter vii%' OR lower(c.text) LIKE '%article 51%' "
        "OR lower(c.text) LIKE '%article 2%' OR lower(c.label) IN "
        "('art. 51','art. 2','art. 39','art. 41','art. 42','art. 33','art. 34','art. 99','preamble')) "
        "ORDER BY d.symbol, c.ordinal LIMIT 14").fetchall()
    if not rows:
        return "No charter or treaty texts are in the library yet. Run fetch.bat for the core pack.", [], "empty"
    blocks = ["## Legal framework\n",
              "The provisions below are quoted from the documents in your library.\n"]
    evidence = []
    for row in rows:
        blocks.append(f"### {row['symbol']} · {row['label']}\n"
                      f"> {row['text'][:600]}\n")
        evidence.append(row["id"])
    return "\n".join(blocks), evidence, "ok"


def section_history(conn, conf: dict) -> tuple[str, list, str]:
    docs = [d for d in _topic_docs(conn, conf.get("topic_id"), 30)
            if d["doc_type"] == "resolution"]
    if not docs:
        return "No resolutions for this agenda are in the library yet.", [], "empty"
    lines = ["## Resolution history\n",
             "| Symbol | Date | Summary | Vote | Adopted |",
             "| --- | --- | --- | --- | --- |"]
    evidence: list = []
    for doc in docs[:8]:
        tally = votes_mod.tally(conn, doc["id"])
        vote_text = (f"Y {tally['in_favour']} / N {tally['against']} / A {tally['abstentions']}"
                     if tally["total"] else "not recorded")
        chunks = conn.execute(
            "SELECT c.id, c.text, c.label FROM chunks c WHERE c.doc_id = ? "
            "AND c.kind IN ('operative','preambular') ORDER BY c.ordinal LIMIT 3",
            (doc["id"],)).fetchall()
        pack_items = [dict(id=row["id"], symbol=doc["symbol"], label=row["label"],
                           text=row["text"], date=doc.get("date"), chunk_id=row["id"])
                      for row in chunks]
        from ..retrieve import pack as packmod

        items, pack_text = packmod.build_pack(pack_items)
        summary = _chat(prompts.BASE_RULES, prompts.render(
            "resolution_summary", pack=pack_text, question=f"{doc['symbol']}"))
        summary = summary.split("\n")[0][:220]
        evidence.extend(i["chunk_id"] for i in items)
        lines.append(f"| {doc['symbol']} | {doc.get('date') or ''} | {summary} | {vote_text} | "
                     f"{'yes' if tally['total'] else '—'} |")
    return "\n".join(lines), evidence, "ok"


def _stance_summary(conn, iso3: str, conf: dict) -> dict:
    payload = {"question": "", "conference": conf, "country": iso3}
    prep = modes.prepare(conn, "stance", payload)
    if prep.get("refusal"):
        return {"text": prep["refusal"], "evidence": [], "refusal": True}
    answer = "".join(modes.generate(prep))
    final = modes.finalize(prep, answer)
    return {"text": final["expanded"], "evidence": prep.get("evidence", []),
            "votes": prep.get("votes", []), "refusal": final["refused"]}


def section_profiles(conn, conf: dict) -> tuple[str, list, str]:
    codes = conf["countries_list"] or countries.UNSC_15
    blocks = ["## Country profiles\n"]
    evidence: list = []
    missing = []
    for iso3 in codes:
        stance = _stance_summary(conn, iso3, conf)
        votes_rows = votes_mod.votes_for_country(conn, iso3, conf.get("topic_id"))
        blocks.append(f"### {countries.name_of(iso3)} ({iso3})\n")
        if votes_rows:
            table = "\n".join(f"- {row['symbol']} ({row.get('date') or 'n.d.'}): **{row['vote']}**"
                              for row in votes_rows[:10])
            blocks.append("**Votes in the library**\n" + table + "\n")
        if stance["refusal"]:
            blocks.append(f"**Position:** {stance['text']}\n")
            missing.append(iso3)
        else:
            blocks.append(f"**Position:** {stance['text']}\n")
            statements = [item for item in stance["evidence"]][:4]
            if statements:
                blocks.append("**Key statements**\n" + "\n".join(
                    f'> "{item["text"][:300]}" — {item["symbol"]}, {item["date"] or ""}'
                    for item in statements) + "\n")
            evidence.extend(item["chunk_id"] for item in stance["evidence"])
    if missing:
        blocks.append("### Data gaps\n\nThe library has no statements for: "
                      + ", ".join(countries.name_of(c) for c in missing) + ".\n")
    return "\n".join(blocks), evidence, "ok"


def _vote_matrix(conn, conf: dict) -> tuple[list[str], list[dict], dict]:
    docs = [d for d in _topic_docs(conn, conf.get("topic_id"), 40) if d["doc_type"] == "resolution"]
    matrix: dict[str, dict[str, str]] = defaultdict(dict)
    for doc in docs:
        for row in votes_mod.members_for(conn, doc["id"]):
            matrix[row["iso3"]][doc["symbol"]] = row["vote"]
    return [d["symbol"] for d in docs], docs, matrix


def _cluster(matrix: dict[str, dict[str, str]], codes: list[str]) -> list[list[str]]:
    def similarity(a: str, b: str) -> float:
        shared = set(matrix.get(a, {})) & set(matrix.get(b, {}))
        if not shared:
            return 0.0
        same = sum(1 for key in shared if matrix[a][key] == matrix[b][key])
        return same / len(shared)

    unassigned = [c for c in codes if matrix.get(c)]
    clusters: list[list[str]] = []
    while unassigned:
        seed = unassigned.pop(0)
        cluster = [seed]
        for other in list(unassigned):
            if similarity(seed, other) >= 0.75:
                cluster.append(other)
                unassigned.remove(other)
        clusters.append(cluster)
    return clusters


def section_blocs(conn, conf: dict) -> tuple[str, list, str]:
    symbols, docs, matrix = _vote_matrix(conn, conf)
    if not symbols or not matrix:
        return ("## Blocs and alliances\n\nNo votes are recorded for this agenda yet, so blocs "
                "cannot be computed. Import voting data (Library → votes CSV) first.\n"), [], "empty"
    codes = conf["countries_list"] or list(matrix)
    clusters = _cluster(matrix, codes)
    lines = ["## Blocs and alliances\n",
             "Clusters come from how countries voted on the resolutions in your library.\n"]
    evidence = []
    for index, cluster in enumerate(clusters, start=1):
        shared = [symbols[i] for i in range(len(symbols))
                  if all(matrix.get(code, {}).get(symbols[i]) ==
                         matrix.get(cluster[0], {}).get(symbols[i]) for code in cluster)]
        lines.append(f"### Group {index}\n")
        lines.append("**Members:** " + ", ".join(countries.name_of(c) for c in cluster) + "\n")
        name = _chat(prompts.BASE_RULES, prompts.render(
            "bloc", pack="Group members: " + ", ".join(cluster) +
                         "\nIdentical votes on: " + ", ".join(shared[:6]),
            question=f"Group {index}"))
        if name and not name.upper().startswith("NOT ENOUGH"):
            lines.append(name + "\n")
        else:
            lines.append(f"Voting together on {len(shared)} of {len(symbols)} resolutions.\n")
    return "\n".join(lines), evidence, "ok"


def section_position(conn, conf: dict) -> tuple[str, list, str]:
    stance = _stance_summary(conn, conf["my_country"], conf)
    md = [f"## My country's position — {countries.name_of(conf['my_country'])}\n",
          stance["text"], "\n### Your official position paper\n",
          "_Paste or edit your position paper here; it is kept with this dossier._\n"]
    if stance.get("votes"):
        md.insert(0, "### Votes in the library\n" + "\n".join(
            f"- {row['symbol']} ({row.get('date') or 'n.d.'}): **{row['vote']}**"
            for row in stance["votes"][:10]) + "\n")
    return "\n".join(md), [i["chunk_id"] for i in stance.get("evidence", [])], "ok"


def section_counter(conn, conf: dict) -> tuple[str, list, str]:
    payload = {"question": f"What objections will other delegations raise against "
                           f"{countries.name_of(conf['my_country'])} on {conf['agenda']}?",
               "conference": conf, "country": conf["my_country"]}
    result = modes.run(conn, "counter", payload)
    if not result["answer"].strip() or result["answer"].upper().startswith("NOT ENOUGH"):
        return "Not enough evidence in the library to prepare counterarguments.", [], "empty"
    md = ("## Likely counterarguments\n\n" +
          result["expanded"] + "\n\n### Evidence\n" + _evidence_links(result["evidence"]))
    return md, [item["chunk_id"] for item in result["evidence"]], "ok"


def section_speech(conn, conf: dict) -> tuple[str, list, str]:
    params = ["hook", "background", "position", "proposed solution", "call to action"]
    evidence: list = []
    sources: list[dict] = []
    paragraphs = []
    for part in params:
        result = service.retrieve(conn, f"{conf['agenda']} {part}", conf)
        if not result["pack"]:
            paragraphs.append(f"[no evidence for the {part} paragraph]")
            continue
        user = prompts.render("speech_para", pack=result["pack_text"], extra=part,
                              question=f"{countries.name_of(conf['my_country'])} on {conf['agenda']}")
        text = _chat(prompts.BASE_RULES, user,
                     temperature=float(config()["llm"]["temperature_draft"]))
        paragraphs.append(text.strip())
        evidence.extend(item["chunk_id"] for item in result["pack"])
        sources.extend({"symbol": item["symbol"], "label": item["label"],
                        "date": item.get("date"), "chunk_id": item["chunk_id"]}
                       for item in result["pack"])
    speech = "\n\n".join(paragraphs)
    words = len(speech.split())
    target = int(conf.get("speech_seconds") or 90) * 130 / 60
    # Trim or expand pass so the speech fits the time limit within about 10 percent.
    for _attempt in range(2):
        if target * 0.9 <= words <= target * 1.1:
            break
        fitted = _chat(
            prompts.BASE_RULES,
            prompts.render("speech_fit", target=int(target), speech=speech),
            temperature=float(config()["llm"]["temperature_draft"]),
        )
        if not fitted or fitted.upper().startswith("NOT ENOUGH"):
            break
        speech = fitted.strip()
        words = len(speech.split())
    # Deterministic fallback: the model sometimes returns an over-long draft unchanged.
    if words > target * 1.1:
        pieces = [s.strip() for s in re.split(r"(?<=[.!?])\s+", speech) if s.strip()]
        kept: list[str] = []
        count = 0
        for sentence in pieces:
            length = len(sentence.split())
            if count + length > target * 1.05:
                break
            kept.append(sentence)
            count += length
        if kept:
            speech = " ".join(kept)
            words = len(speech.split())
    md = [f"## Opening speech — {countries.name_of(conf['my_country'])}\n",
          f"_Target: {conf.get('speech_seconds') or 90} seconds "
          f"(about {int(target)} words). Current length: {words} words._\n", speech, "\n### Sources\n",
          _evidence_links(list({(s["symbol"], s["label"], s["chunk_id"]): s
                                for s in sources}.values()))]
    return "\n".join(md), evidence, "ok"


def section_working_paper(conn, conf: dict) -> tuple[str, list, str]:
    result = service.retrieve(conn, conf["agenda"], conf)
    if not result["pack"]:
        return "No evidence in the library for a working paper.", [], "empty"
    pre_user = prompts.render("wp_preamble", pack=result["pack_text"], extra="3",
                              question=conf["agenda"])
    preamble = _chat(prompts.BASE_RULES, pre_user,
                     temperature=float(config()["llm"]["temperature_draft"]))
    themes = ["security and policing", "humanitarian access", "political process",
              "sanctions and enforcement", "financing", "monitoring and reporting"]
    clauses = []
    for theme in themes:
        user = prompts.render("wp_operative", pack=result["pack_text"], extra=theme,
                              question=countries.name_of(conf["my_country"]))
        clause = _chat(prompts.BASE_RULES, user,
                       temperature=float(config()["llm"]["temperature_draft"]))
        clauses.append(clause.strip())
    body = "\n\n".join(f"{index}. {clause}" for index, clause in enumerate(clauses, start=1))
    symbols = {row["symbol"] for row in conn.execute(
        "SELECT symbol FROM documents WHERE symbol IS NOT NULL").fetchall()}
    missing = guards.validate_resolution_refs(preamble + "\n" + body, symbols)
    warning = ""
    if missing:
        warning = ("\n> **Validator warning:** these references are not in your library: "
                   + ", ".join(missing) + ". Remove or verify them before use.\n")
    votes_note = ""
    md = [f"## Working paper — {conf['committee']}\n",
          f"**Agenda:** {conf['agenda']}  \n**Sponsor:** {countries.name_of(conf['my_country'])}\n",
          warning,
          "### Preambular clauses\n", preamble, "\n### Operative clauses\n", body,
          "\n### Evidence appendix\n",
          _evidence_links(result["pack"])]
    return "\n".join(md), [item["chunk_id"] for item in result["pack"]], "ok"


def section_pois(conn, conf: dict) -> tuple[str, list, str]:
    codes = conf["countries_list"] or countries.UNSC_15
    blocks = ["## POIs and follow-ups\n"]
    cards = 0
    evidence_all = []
    for iso3 in codes:
        stance = _stance_summary(conn, iso3, conf)
        statements = stance.get("evidence", [])[:2]
        votes_rows = stance.get("votes", [])
        tension = None
        if len(statements) >= 1 and votes_rows:
            votes_line = "; ".join(f"{row['symbol']}: {row['vote']}" for row in votes_rows[:4])
            tension = (f"Statements:\n" + "\n".join(
                f"- {s['text'][:500]}" for s in statements) +
                f"\nVotes:\n{votes_line}")
        elif len(statements) >= 2:
            tension = "Two statements by the same country:\n" + "\n".join(
                f"- {s['text'][:400]}" for s in statements)
        if not tension:
            blocks.append(f"### {countries.name_of(iso3)}\n\n"
                          "No strong angle found for this country.\n")
            continue
        prompt = prompts.render("poi_card", pack=tension,
                                question=f"Write a POI card about {countries.name_of(iso3)} "
                                         f"on {conf['agenda']}.")
        raw = _chat(prompts.BASE_RULES, prompt, temperature=0.3)
        card = _parse_json(raw)
        evidence_items = statements if statements else []
        if not card or len(evidence_items) < 1:
            blocks.append(f"### {countries.name_of(iso3)}\n\n"
                          "No strong angle found for this country.\n")
            continue
        cards += 1
        blocks.append(f"### {countries.name_of(iso3)}\n")
        blocks.append(f"**Question:** {card.get('question', '')}\n")
        for item in evidence_items:
            blocks.append(f'> "{item["text"][:300]}" — {item["symbol"]}, {item["date"] or ""}')
        if votes_rows:
            blocks.append("\n**Votes:** " + "; ".join(
                f"{row['symbol']} = {row['vote']}" for row in votes_rows[:5]))
        blocks.append(f"\n**If they say yes:** {card.get('if_yes', '')}")
        blocks.append(f"**If they say no:** {card.get('if_no', '')}")
        blocks.append(f"**Follow-up:** {card.get('follow_up', '')}\n")
        evidence_all.extend(item["chunk_id"] for item in evidence_items)
    blocks.insert(1, f"_{cards} cards generated. Every card shows its evidence so you can "
                     f"verify it before committee._\n")
    return "\n".join(blocks), evidence_all, "ok"


def _parse_json(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


BUILDERS = {
    "background": section_background,
    "legal": section_legal,
    "history": section_history,
    "profiles": section_profiles,
    "blocs": section_blocs,
    "position": section_position,
    "counter": section_counter,
    "speech": section_speech,
    "working_paper": section_working_paper,
    "pois": section_pois,
}


def build(conn, job_id: int, conference_id: int, only: str | None = None) -> None:
    from .. import jobs

    conf = _conf(conn, conference_id)
    todo = [(key, title) for key, title in SECTIONS if not only or key == only]
    for index, (key, title) in enumerate(todo):
        jobs.update(conn, job_id, progress=round(index / max(len(todo), 1), 2),
                    message=f"Building {title}")
        builder = BUILDERS[key]
        try:
            md, evidence, status = builder(conn, conf)
        except Exception as exc:  # noqa: BLE001 - keep earlier sections
            md, evidence, status = (f"> This section failed: {exc}\n\n"
                                    "The other sections are unaffected."), [], "error"
        _save(conn, conference_id, key, md, evidence, status=status)
    jobs.update(conn, job_id, progress=1.0,
                message=f"Dossier ready ({SECTION_TITLES.get(only, 'all sections')})")
