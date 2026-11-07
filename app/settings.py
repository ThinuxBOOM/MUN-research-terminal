"""Configuration loading: config.yaml, then environment, then the settings table."""
from __future__ import annotations

import copy
import os
import threading
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "mun.db"
LOG_DIR = DATA_DIR / "logs"
CORPUS_RAW = ROOT / "corpus" / "raw"
CORPUS_INBOX = ROOT / "corpus" / "inbox"
MANIFEST_DIR = ROOT / "corpus" / "manifests"
PROMPT_DIR = Path(__file__).resolve().parent / "llm" / "prompts"

DEFAULTS = {
    "app": {"host": "127.0.0.1", "port": 8765, "title": "MUN Research Station"},
    "llm": {
        "base_url": "http://localhost:11434",
        "model": "qwen3-mun",
        "embed_model": "qwen3-embedding:0.6b",
        "context_length": 8192,
        "temperature_evidence": 0.2,
        "temperature_draft": 0.5,
        "allow_thinking": False,
        "max_answer_tokens": 700,
        "request_timeout": 180,
    },
    "retrieval": {
        "fts_top_k": 30,
        "vec_top_k": 30,
        "rerank_top_k": 8,
        "min_rerank_score": 0.20,
        "pack_token_budget": 3500,
        "graph_hops": 1,
        "graph_seed_chunks": 3,
        "graph_per_seed": 4,
    },
    "ingest": {"chunk_target_tokens": 300, "chunk_max_tokens": 500, "min_topic_hits": 2},
    "ui": {"theme": "dark"},
}

_lock = threading.Lock()
_cache: dict | None = None
_cache_at = 0.0


def _merge(base: dict, extra: dict) -> dict:
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_file() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            _merge(cfg, yaml.safe_load(fh) or {})
    if os.getenv("MUN_LLM_BASE_URL"):
        cfg["llm"]["base_url"] = os.environ["MUN_LLM_BASE_URL"]
    if os.getenv("MUN_LLM_MODEL"):
        cfg["llm"]["model"] = os.environ["MUN_LLM_MODEL"]
    if os.getenv("MUN_EMBED_MODEL"):
        cfg["llm"]["embed_model"] = os.environ["MUN_EMBED_MODEL"]
    return cfg


def config() -> dict:
    """Config with settings-table overrides applied (cached for 5 seconds)."""
    global _cache, _cache_at
    now = time.time()
    with _lock:
        if _cache is not None and now - _cache_at < 5:
            return _cache
    cfg = _load_file()
    try:
        from .db import connect  # local import avoids a cycle

        conn = connect()
        try:
            for row in conn.execute("SELECT key, value FROM settings"):
                parts = row["key"].split(".")
                node = cfg
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                raw = row["value"]
                if raw in ("true", "false"):
                    node[parts[-1]] = raw == "true"
                else:
                    try:
                        node[parts[-1]] = int(raw)
                    except (TypeError, ValueError):
                        node[parts[-1]] = raw
        finally:
            conn.close()
    except Exception:
        pass
    with _lock:
        _cache = cfg
        _cache_at = now
    return cfg


def clear_cache() -> None:
    global _cache, _cache_at
    with _lock:
        _cache = None
        _cache_at = 0.0


def get(dotted: str, default=None):
    node = config()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def native_llm_base() -> str:
    """Ollama native API root, derived from the configured base URL."""
    base = str(get("llm.base_url", "http://localhost:11434")).rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base
