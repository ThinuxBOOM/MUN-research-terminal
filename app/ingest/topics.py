"""Topic definitions and keyword tagging (plan 6.6)."""
from __future__ import annotations

import json
import re

from ..settings import config

DEFAULT_TOPICS: dict[str, list[str]] = {
    "Haiti": ["Haiti", "Haitian", "BINUH", "Port-au-Prince", "Multinational Security Support",
              "MSS", "Gang Suppression Force", "Haiti sanctions", "MINUJUSTH", "MINUSTAH"],
    "Use of force": ["use of force", "Article 51", "self-defence", "self-defense",
                     "armed attack", "Chapter VII"],
    "Peacekeeping": ["peacekeeping", "peace operation", "blue helmets", "mission mandate",
                     "troop-contributing"],
    "Sanctions": ["sanctions", "embargo", "asset freeze", "travel ban", "sanctions committee"],
    "Climate": ["climate change", "emissions", "global warming", "Paris Agreement"],
    "Human rights": ["human rights", "Universal Declaration", "civil and political",
                     "economic, social and cultural"],
    "Women, peace and security": ["women, peace and security", "resolution 1325",
                                  "gender-based violence", "sexual violence in conflict"],
    "International law": ["international law", "Vienna Convention", "law of treaties",
                          "customary international law"],
    "Terrorism": ["terrorism", "terrorist", "counter-terrorism", "ISIL", "Al-Qaida"],
    "Nuclear non-proliferation": ["non-proliferation", "nuclear weapon", "NPT", "IAEA"],
}


def seed(conn) -> None:
    for name, keywords in DEFAULT_TOPICS.items():
        conn.execute(
            "INSERT INTO topics(name, keywords) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET keywords = excluded.keywords",
            (name, json.dumps(keywords)),
        )
    conn.commit()


def topic_id(conn, name: str) -> int | None:
    row = conn.execute("SELECT id FROM topics WHERE lower(name) = lower(?)", (name,)).fetchone()
    return row["id"] if row else None


def tag_document(conn, doc_id: int, text: str) -> list[str]:
    """Keyword tagging with a minimum hit count; manual tags are preserved."""
    minimum = int(config()["ingest"]["min_topic_hits"])
    assigned = []
    for row in conn.execute("SELECT id, name, keywords FROM topics").fetchall():
        keywords = json.loads(row["keywords"] or "[]")
        hits = 0
        for keyword in keywords:
            if re.search(r"\b" + re.escape(keyword) + r"\b", text, re.I):
                hits += 1
        if hits >= minimum:
            conn.execute(
                "INSERT INTO doc_topics(doc_id, topic_id, origin) VALUES (?, ?, 'keyword') "
                "ON CONFLICT(doc_id, topic_id) DO NOTHING", (doc_id, row["id"]))
            assigned.append(row["name"])
    conn.commit()
    return assigned


def docs_for_topic(conn, topic: str) -> list[int]:
    row = conn.execute("SELECT id FROM topics WHERE lower(name) = lower(?)", (topic,)).fetchone()
    if not row:
        return []
    return [r["doc_id"] for r in conn.execute(
        "SELECT doc_id FROM doc_topics WHERE topic_id = ?", (row["id"],)).fetchall()]


def add_topic(conn, name: str, keywords: list[str]) -> int:
    conn.execute(
        "INSERT INTO topics(name, keywords) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET keywords = excluded.keywords",
        (name, json.dumps(keywords)),
    )
    conn.commit()
    return topic_id(conn, name)
