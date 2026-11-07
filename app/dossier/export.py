"""Dossier export: Markdown and DOCX (plan 3, section 11)."""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.shared import Pt

from ..settings import DATA_DIR

EXPORT_DIR = DATA_DIR / "exports"


def _sections(conn, conference_id: int) -> tuple[dict, list[dict]]:
    conf_row = conn.execute("SELECT * FROM conferences WHERE id = ?", (conference_id,)).fetchone()
    conf = dict(conf_row) if conf_row else {"name": "Dossier", "agenda": "", "committee": ""}
    rows = conn.execute(
        "SELECT * FROM dossier_sections WHERE conference_id = ? ORDER BY id",
        (conference_id,)).fetchall()
    return conf, [dict(row) for row in rows]


def to_markdown(conn, conference_id: int) -> str:
    conf, sections = _sections(conn, conference_id)
    head = [f"# {conf.get('name') or 'MUN dossier'}\n",
            f"**Committee:** {conf.get('committee') or ''}  ",
            f"**Agenda:** {conf.get('agenda') or ''}  ",
            f"**Country:** {conf.get('my_country') or ''}\n"]
    body = [row["content_md"] or "" for row in sections]
    return "\n".join(head + body)


def to_docx(conn, conference_id: int) -> Path:
    conf, sections = _sections(conn, conference_id)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    doc.add_heading(conf.get("name") or "MUN dossier", level=0)
    doc.add_paragraph(f"Committee: {conf.get('committee') or ''}")
    doc.add_paragraph(f"Agenda: {conf.get('agenda') or ''}")
    doc.add_paragraph(f"Country: {conf.get('my_country') or ''}")
    for row in sections:
        for line in (row["content_md"] or "").split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("### "):
                doc.add_heading(stripped[4:], level=2)
            elif stripped.startswith("## "):
                doc.add_heading(stripped[3:], level=1)
            elif stripped.startswith("# "):
                doc.add_heading(stripped[2:], level=0)
            elif stripped.startswith(("- ", "* ")):
                doc.add_paragraph(re.sub(r"^[-*]\s+", "", stripped), style="List Bullet")
            elif re.match(r"^\d+\.\s", stripped):
                doc.add_paragraph(re.sub(r"^\d+\.\s+", "", stripped), style="List Number")
            elif stripped.startswith(">"):
                doc.add_paragraph(stripped.lstrip("> ").strip(), style="Intense Quote")
            elif stripped.startswith("|") or stripped.startswith("**"):
                doc.add_paragraph(stripped.replace("**", "").replace("|", "  "))
            else:
                doc.add_paragraph(stripped.replace("**", ""))
    target = EXPORT_DIR / f"dossier-{conference_id}.docx"
    doc.save(str(target))
    return target
