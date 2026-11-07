"""HTTP routes: home, library, ask, dossier, connections, settings, jobs."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.templating import Jinja2Templates

from .. import jobs
from ..db import connect, table_count
from ..dossier import export as dossier_export
from ..dossier import pipeline as dossier_pipeline
from ..ingest import countries, topics, votes as votes_mod
from ..ingest.pipeline import ingest_file, ingest_folder
from ..llm.client import LLMClient
from ..modes import service as modes
from ..retrieve import search
from ..settings import CORPUS_INBOX, get
from ..db import get_setting, set_setting

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _health(conn) -> dict:
    llm = LLMClient()
    status = llm.health()
    status["docs"] = table_count(conn, "documents")
    status["chunks"] = table_count(conn, "chunks")
    status["vectors"] = table_count(conn, "chunk_vec")
    status["votes"] = table_count(conn, "votes")
    status["edges"] = table_count(conn, "edges")
    status["pending_edges"] = conn.execute(
        "SELECT COUNT(*) AS n FROM edges WHERE status='pending'").fetchone()["n"]
    return status


def _conference(conn, conference_id: int | None) -> dict | None:
    if not conference_id:
        return None
    row = conn.execute("SELECT * FROM conferences WHERE id = ?", (conference_id,)).fetchone()
    if not row:
        return None
    conf = dict(row)
    conf["countries_list"] = json.loads(conf.get("countries") or "[]")
    return conf


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = connect()
    conferences = [dict(row) for row in conn.execute(
        "SELECT * FROM conferences ORDER BY id DESC").fetchall()]
    health = _health(conn)
    conn.close()
    return templates.TemplateResponse(request, "home.html", {
        "conferences": conferences, "health": health, "active": "home",
    })


@router.post("/health")
def health():
    conn = connect()
    try:
        return JSONResponse(_health(conn))
    finally:
        conn.close()


# ------------------------------------------------------------------- library
@router.get("/library", response_class=HTMLResponse)
def library(request: Request, q: str = ""):
    conn = connect()
    if q:
        rows = conn.execute(
            "SELECT * FROM documents WHERE symbol LIKE ? OR title LIKE ? ORDER BY date DESC",
            (f"%{q}%", f"%{q}%")).fetchall()
    else:
        rows = conn.execute("SELECT * FROM documents ORDER BY date DESC").fetchall()
    docs = []
    for row in rows:
        item = dict(row)
        item["chunks"] = table_count_filtered(conn, row["id"])
        docs.append(item)
    tags = conn.execute(
        "SELECT t.name, COUNT(dt.doc_id) AS n FROM topics t "
        "LEFT JOIN doc_topics dt ON dt.topic_id = t.id GROUP BY t.id ORDER BY t.name").fetchall()
    health = _health(conn)
    conn.close()
    return templates.TemplateResponse(request, "library.html", {
        "documents": docs, "tags": [dict(t) for t in tags], "q": q,
        "health": health, "active": "library",
        "inbox": str(CORPUS_INBOX),
    })


def table_count_filtered(conn, doc_id: int) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM chunks WHERE doc_id = ?",
                        (doc_id,)).fetchone()["n"]


@router.post("/library/upload")
async def upload(request: Request, files: list[UploadFile] = File(default=[])):
    conn = connect()
    results = []
    for upload_file in files or []:
        if not upload_file.filename:
            continue
        target = CORPUS_INBOX / upload_file.filename
        with target.open("wb") as fh:
            shutil.copyfileobj(upload_file.file, fh)
        try:
            results.append(ingest_file(conn, target))
        except Exception as exc:  # noqa: BLE001
            results.append({"status": "error", "file": upload_file.filename, "message": str(exc)})
    conn.close()
    return JSONResponse({"results": results})


@router.post("/library/ingest-inbox")
def ingest_inbox():
    conn = connect()
    results = ingest_folder(conn, CORPUS_INBOX)
    conn.close()
    return JSONResponse({"results": results})


# ----------------------------------------------------------------------- ask
@router.get("/ask", response_class=HTMLResponse)
def ask(request: Request, conference_id: int | None = None, q: str = ""):
    conn = connect()
    conferences = [dict(row) for row in conn.execute("SELECT * FROM conferences").fetchall()]
    conf = _conference(conn, conference_id) or (_conference(conn, conferences[0]["id"])
                                                if conferences else None)
    recent = [dict(row) for row in conn.execute(
        "SELECT * FROM notes ORDER BY id DESC LIMIT 10").fetchall()]
    health = _health(conn)
    conn.close()
    return templates.TemplateResponse(request, "ask.html", {
        "conferences": conferences, "conference": conf, "health": health,
        "recent": recent, "q": q, "active": "ask",
        "modes": [("evidence", "Evidence"), ("stance", "Stance"), ("connect", "Connect"),
                  ("argue", "Argue"), ("counter", "Counter"), ("check", "Check clause")],
        "country_options": countries.COUNTRIES,
    })


@router.post("/api/ask")
def ask_stream(request: Request, question: str = Form(...), mode: str = Form("evidence"),
               conference_id: int = Form(0), country: str = Form(""),
               doc_a: str = Form(""), doc_b: str = Form("")):
    conn = connect()
    try:
        conf = _conference(conn, conference_id or None)
        payload = {"question": question, "mode": mode, "conference": conf,
                   "country": country or None, "doc_a": doc_a, "doc_b": doc_b}
        prep = modes.prepare(conn, mode, payload)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)
    finally:
        # The streaming generator runs on another thread; it opens its own connection.
        conn.close()

    def stream():
        yield "event: evidence\ndata: " + json.dumps({
            "evidence": prep.get("evidence", []),
            "votes": prep.get("votes", []),
            "meta": prep.get("meta", {}),
            "refusal": prep.get("refusal"),
            "retrieval_ms": prep.get("meta", {}).get("retrieval_ms", 0),
        }, default=str) + "\n\n"
        buffer: list[str] = []
        try:
            for token in modes.generate(prep):
                buffer.append(token)
                yield "event: token\ndata: " + json.dumps({"text": token}) + "\n\n"
        except Exception as exc:  # noqa: BLE001
            yield "event: error\ndata: " + json.dumps({"message": str(exc)}) + "\n\n"
            return
        answer = "".join(buffer)
        final = modes.finalize(prep, answer)
        final["evidence"] = prep.get("evidence", [])
        final["votes"] = prep.get("votes", [])
        final["meta"] = prep.get("meta", {})
        yield "event: done\ndata: " + json.dumps(final, default=str) + "\n\n"
        try:
            log = connect()
            log.execute(
                "INSERT INTO notes(conference_id, text, created_at) VALUES (?, ?, ?)",
                (conference_id or None, question, datetime.now().isoformat(timespec="seconds")))
            log.commit()
            log.close()
        except Exception:  # noqa: BLE001
            pass

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/api/pin-note")
def pin_note(chunk_id: int = Form(...), conference_id: int = Form(0), text: str = Form("")):
    conn = connect()
    conn.execute("INSERT INTO notes(conference_id, chunk_id, text, created_at) VALUES (?,?,?,?)",
                 (conference_id or None, chunk_id, text[:400],
                  datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})


# ------------------------------------------------------------------ dossier
@router.get("/dossier/{conference_id}", response_class=HTMLResponse)
def dossier(request: Request, conference_id: int, section: str = ""):
    conn = connect()
    conf = _conference(conn, conference_id)
    if not conf:
        conn.close()
        return RedirectResponse("/")
    sections = [dict(row) for row in conn.execute(
        "SELECT * FROM dossier_sections WHERE conference_id = ? ORDER BY id",
        (conference_id,)).fetchall()]
    current = None
    if sections:
        current = next((s for s in sections if s["section"] == section), sections[0])
    health = _health(conn)
    conn.close()
    return templates.TemplateResponse(request, "dossier.html", {
        "conference": conf, "sections": sections, "current": current,
        "health": health, "active": "dossier",
    })


@router.post("/dossier/{conference_id}/build")
def build_dossier(conference_id: int, section: str = Form("")):
    conn = connect()
    job_id = jobs.create(conn, "dossier", {"conference_id": conference_id, "section": section})
    jobs.run_async(job_id, dossier_pipeline.build, conference_id, section or None)
    conn.close()
    return JSONResponse({"job_id": job_id})


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    conn = connect()
    rows = jobs.recent(conn, 30)
    health = _health(conn)
    conn.close()
    return templates.TemplateResponse(request, "jobs.html", {
        "jobs": rows, "health": health, "active": "jobs"})


@router.get("/api/jobs/{job_id}")
def job_status(job_id: int):
    conn = connect()
    item = jobs.get(conn, job_id)
    conn.close()
    return JSONResponse(item or {})


# -------------------------------------------------------------- connections
@router.get("/connections", response_class=HTMLResponse)
def connections(request: Request, doc_id: int | None = None):
    conn = connect()
    pending = [dict(row) for row in conn.execute(
        "SELECT e.*, s.symbol AS src_symbol, d.symbol AS dst_symbol "
        "FROM edges e LEFT JOIN documents s ON s.id = e.src_id "
        "LEFT JOIN documents d ON d.id = e.dst_id WHERE e.status='pending' "
        "ORDER BY e.id DESC LIMIT 100").fetchall()]
    accepted = [dict(row) for row in conn.execute(
        "SELECT e.*, s.symbol AS src_symbol, d.symbol AS dst_symbol "
        "FROM edges e LEFT JOIN documents s ON s.id = e.src_id "
        "LEFT JOIN documents d ON d.id = e.dst_id WHERE e.status='accepted' "
        "ORDER BY e.id DESC LIMIT 100").fetchall()]
    health = _health(conn)
    conn.close()
    return templates.TemplateResponse(request, "connections.html", {
        "pending": pending, "accepted": accepted, "health": health, "active": "connections"})


@router.post("/connections/{edge_id}/{action}")
def review_edge(edge_id: int, action: str):
    status = {"accept": "accepted", "reject": "rejected"}.get(action)
    if not status:
        return JSONResponse({"error": "unknown action"}, status_code=400)
    conn = connect()
    conn.execute("UPDATE edges SET status = ? WHERE id = ?", (status, edge_id))
    conn.commit()
    conn.close()
    return RedirectResponse("/connections", status_code=303)


# ----------------------------------------------------------------- settings
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    conn = connect()
    health = _health(conn)
    client = LLMClient()
    ctx = client.context_length()
    stored = {row["key"]: row["value"] for row in conn.execute("SELECT * FROM settings")}
    conn.close()
    return templates.TemplateResponse(request, "settings.html", {
        "health": health, "cfg": get("llm"), "theme": get("ui.theme"),
        "stored": stored, "context": ctx, "active": "settings",
        "threshold": get("retrieval.min_rerank_score"),
    })


@router.post("/settings")
def save_settings(base_url: str = Form(...), model: str = Form(...),
                  embed_model: str = Form(...), context_length: int = Form(8192),
                  min_rerank_score: float = Form(0.2), theme: str = Form("dark"),
                  allow_thinking: str = Form("off")):
    conn = connect()
    for key, value in {
        "llm.base_url": base_url, "llm.model": model, "llm.embed_model": embed_model,
        "llm.context_length": context_length, "retrieval.min_rerank_score": min_rerank_score,
        "ui.theme": theme, "llm.allow_thinking": allow_thinking == "on",
    }.items():
        set_setting(conn, key, value)
    conn.commit()
    conn.close()
    from ..settings import clear_cache

    clear_cache()
    return RedirectResponse("/settings", status_code=303)


# -------------------------------------------------------------- conferences
@router.get("/conferences/new", response_class=HTMLResponse)
def new_conference(request: Request):
    conn = connect()
    topic_rows = [dict(row) for row in conn.execute("SELECT * FROM topics ORDER BY name")]
    health = _health(conn)
    conn.close()
    return templates.TemplateResponse(request, "new_conference.html", {
        "topics": topic_rows, "health": health, "active": "home",
        "country_options": countries.COUNTRIES, "unsc": countries.UNSC_15,
        "committees": ["UNSC", "UNGA plenary", "GA First Committee", "GA Second Committee",
                       "GA Third Committee", "GA Fourth Committee", "GA Fifth Committee",
                       "GA Sixth Committee", "Other"],
    })


@router.post("/conferences")
def create_conference(name: str = Form(...), committee: str = Form("UNSC"),
                      agenda: str = Form(...), my_country: str = Form(...),
                      speech_seconds: int = Form(90), want_working_paper: str = Form("on"),
                      topic: str = Form(""), countries_json: str = Form("[]")):
    conn = connect()
    topic_id = topics.topic_id(conn, topic) if topic else None
    cursor = conn.execute(
        "INSERT INTO conferences(name, committee, agenda, my_country, countries, topic_id, "
        "speech_seconds, want_working_paper, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (name, committee, agenda, my_country, countries_json, topic_id, speech_seconds,
         1 if want_working_paper == "on" else 0,
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conference_id = int(cursor.lastrowid)
    conn.close()
    return RedirectResponse(f"/dossier/{conference_id}", status_code=303)


@router.get("/api/coverage")
def coverage(topic: str = "", countries_param: str = ""):
    conn = connect()
    tid = topics.topic_id(conn, topic)
    docs = conn.execute(
        "SELECT COUNT(DISTINCT doc_id) AS n FROM doc_topics WHERE topic_id = ?",
        (tid,)).fetchone()["n"] if tid else table_count(conn, "documents")
    vote_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM votes v JOIN doc_topics dt ON dt.doc_id = v.doc_id "
        "WHERE dt.topic_id = ?", (tid,)).fetchone()["n"] if tid else 0
    requested = [c for c in (countries_param or "").split(",") if c]
    gaps = []
    for iso3 in requested:
        has = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks c JOIN documents d ON d.id = c.doc_id "
            "WHERE c.speaker_country = ? AND (? IS NULL OR d.id IN "
            "(SELECT doc_id FROM doc_topics WHERE topic_id = ?))",
            (iso3, tid, tid)).fetchone()["n"]
        if not has:
            gaps.append(iso3)
    conn.close()
    verdict = "good" if docs >= 5 and not gaps else ("thin" if docs else "empty")
    return JSONResponse({"documents": docs, "votes": vote_rows, "countries_without_data": gaps,
                         "verdict": verdict})


# ------------------------------------------------------------------ exports
@router.get("/export/{conference_id}.md")
def export_markdown(conference_id: int):
    conn = connect()
    text = dossier_export.to_markdown(conn, conference_id)
    conn.close()
    return StreamingResponse(iter([text]), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition":
                                      f"attachment; filename=dossier-{conference_id}.md"})


@router.get("/export/{conference_id}.docx")
def export_docx(conference_id: int):
    conn = connect()
    path = dossier_export.to_docx(conn, conference_id)
    conn.close()
    return FileResponse(
        str(path), filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# --------------------------------------------------------------------- votes
@router.get("/votes", response_class=HTMLResponse)
def votes_page(request: Request, doc_id: int | None = None):
    conn = connect()
    resolutions = [dict(row) for row in conn.execute(
        "SELECT id, symbol, title, date FROM documents WHERE doc_type = 'resolution' "
        "AND status = 'ok' ORDER BY date DESC, symbol").fetchall()]
    rows = [dict(row) for row in conn.execute(
        "SELECT v.id, v.vote, v.source, d.symbol, d.date, COALESCE(c.name, v.iso3) AS country "
        "FROM votes v JOIN documents d ON d.id = v.doc_id "
        "LEFT JOIN countries c ON c.iso3 = v.iso3 ORDER BY d.date DESC, d.symbol, country").fetchall()]
    tallies = {doc["id"]: votes_mod.tally(conn, doc["id"]) for doc in resolutions}
    health = _health(conn)
    conn.close()
    return templates.TemplateResponse(request, "votes.html", {
        "resolutions": resolutions, "votes": rows, "tallies": tallies,
        "country_options": countries.COUNTRIES, "health": health, "active": "votes",
    })


@router.post("/votes/add")
def add_vote_manual(doc_id: int = Form(...), iso3: str = Form(...), vote: str = Form(...)):
    conn = connect()
    ok = votes_mod.add_vote(conn, doc_id, iso3, vote, "manual")
    conn.commit()
    conn.close()
    return RedirectResponse("/votes" if ok else "/votes?error=1", status_code=303)


@router.post("/votes/upload")
async def upload_votes(file: UploadFile = File(...)):
    conn = connect()
    target = CORPUS_INBOX / (file.filename or "votes.csv")
    with target.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    summary = votes_mod.import_csv(conn, target)
    conn.close()
    return JSONResponse(summary)


@router.get("/export/section/{section_id}.md")
def export_section(section_id: int):
    conn = connect()
    row = conn.execute("SELECT * FROM dossier_sections WHERE id = ?", (section_id,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    return StreamingResponse(iter([row["content_md"] or ""]),
                             media_type="text/markdown; charset=utf-8")
