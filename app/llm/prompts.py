"""Prompt loading and rendering. One small file per bounded task."""
from __future__ import annotations

import re

from ..settings import PROMPT_DIR

_cache: dict[str, str] = {}

BASE_RULES = (
    "You are an evidence assistant for a Model UN delegate. Use ONLY the numbered passages "
    "below. Every sentence you write must end with passage markers like [S2]. If the passages "
    "do not answer the task, reply exactly: NOT ENOUGH EVIDENCE. Never invent resolution "
    "numbers, dates, vote counts or quotes. Do not use knowledge from outside the passages."
)


def raw(name: str) -> str:
    if name in _cache:
        return _cache[name]
    path = PROMPT_DIR / f"{name}.txt"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    _cache[name] = text
    return text


def render(name: str, **values) -> str:
    text = raw(name)
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def build(name: str, pack: str, question: str, extra: str = "") -> tuple[str, str]:
    """Return (system, user) for a standard evidence task."""
    system = BASE_RULES
    user = render(name, pack=pack, question=question, extra=extra)
    return system, user


def parse_markers(text: str) -> list[str]:
    return re.findall(r"\[(S\d+)\]", text or "")


def strip_markers(text: str) -> str:
    return re.sub(r"\s*\[S\d+\]", "", text or "")
