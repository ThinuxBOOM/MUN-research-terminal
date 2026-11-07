"""Ollama client: chat, streaming, structured JSON, embeddings.

The native /api/chat endpoint is used because it honours num_ctx per request.
The OpenAI-compatible /v1 endpoint is still accepted as a base URL (see
settings.native_llm_base), so any compatible server can be configured.
"""
from __future__ import annotations

import json
import re
import time
from typing import Iterator

import httpx

from ..settings import config, native_llm_base

_THINK_BLOCK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S | re.I)
_THINK_OPEN = re.compile(r"<think(?:ing)?>", re.I)

NO_THINK = "/no_think"


def strip_think(text: str) -> str:
    """Remove Qwen3 reasoning blocks, including an unterminated trailing one."""
    if not text:
        return ""
    text = _THINK_BLOCK.sub("", text)
    match = _THINK_OPEN.search(text)
    if match:
        tail = text[match.end():]
        close = re.search(r"</think(?:ing)?>", tail, re.I)
        if close:
            text = text[: match.start()] + tail[close.end():]
        else:
            text = text[: match.start()]
    return text.strip()


class ThinkStripper:
    """Streaming filter that hides think blocks split across SSE chunks."""

    def __init__(self) -> None:
        self.buf = ""
        self.in_think = False

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = []
        while self.buf:
            if not self.in_think:
                idx = self.buf.lower().find("<think")
                if idx == -1:
                    keep = self._partial_tag_tail(self.buf)
                    out.append(self.buf[: len(self.buf) - keep])
                    self.buf = self.buf[len(self.buf) - keep:] if keep else ""
                    break
                out.append(self.buf[:idx])
                self.buf = self.buf[idx:]
                end = self.buf.find(">")
                if end == -1:
                    break
                self.buf = self.buf[end + 1:]
                self.in_think = True
            else:
                idx = self.buf.lower().find("</think")
                if idx == -1:
                    self.buf = self.buf[-16:]
                    break
                end = self.buf.find(">", idx)
                if end == -1:
                    break
                self.buf = self.buf[end + 1:]
                self.in_think = False
        return "".join(out)

    @staticmethod
    def _partial_tag_tail(text: str) -> int:
        low = text.lower()
        for size in range(min(7, len(low)), 0, -1):
            if "<think"[:size] == low[-size:]:
                return size
        return 0

    def flush(self) -> str:
        rest = "" if self.in_think else self.buf
        self.buf = ""
        return rest


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        cfg = config()["llm"]
        self.base = native_llm_base()
        self.model = cfg["model"]
        self.embed_model = cfg["embed_model"]
        self.num_ctx = int(cfg["context_length"])
        self.timeout = float(cfg["request_timeout"])
        self.default_max = int(cfg["max_answer_tokens"])
        self.allow_thinking = bool(cfg["allow_thinking"])

    # ---------------------------------------------------------------- helpers
    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def _messages(self, system: str, user: str, think: bool) -> list[dict]:
        if not think and not user.rstrip().endswith(NO_THINK):
            user = f"{user}\n{NO_THINK}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _options(self, temperature: float, max_tokens: int, think: bool) -> dict:
        return {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": self.num_ctx,
        }, think

    @staticmethod
    def friendly(exc: Exception) -> str:
        text = str(exc)
        if isinstance(exc, httpx.ConnectError):
            return ("Cannot reach Ollama. Start it with 'ollama serve' or open the Ollama app, "
                    "then check the endpoint in Settings.")
        if isinstance(exc, httpx.ReadTimeout):
            return ("Ollama took too long to answer. The model may still be loading; "
                    "try again, or use a shorter question.")
        if "not found" in text.lower() and "model" in text.lower():
            return ("The configured model is not installed. Run install.bat, or run "
                    "'ollama pull qwen3:8b' and 'ollama create qwen3-mun -f Modelfile'.")
        return f"LLM call failed: {text}"

    # ------------------------------------------------------------------- chat
    def chat(self, system: str, user: str, temperature: float = 0.2,
             max_tokens: int | None = None, think: bool | None = None,
             json_schema: dict | None = None) -> str:
        think = self.allow_thinking if think is None else think
        options, think = self._options(temperature, max_tokens or self.default_max, think)
        payload = {
            "model": self.model,
            "messages": self._messages(system, user, think),
            "stream": False,
            "think": bool(think),
            "options": options,
        }
        if json_schema is not None:
            payload["format"] = json_schema
        try:
            resp = httpx.post(self._url("/api/chat"), json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - surfaced as plain English
            raise LLMError(self.friendly(exc)) from exc
        return strip_think((data.get("message") or {}).get("content", ""))

    def stream(self, system: str, user: str, temperature: float = 0.2,
               max_tokens: int | None = None, think: bool | None = None) -> Iterator[str]:
        think = self.allow_thinking if think is None else think
        options, think = self._options(temperature, max_tokens or self.default_max, think)
        payload = {
            "model": self.model,
            "messages": self._messages(system, user, think),
            "stream": True,
            "think": bool(think),
            "options": options,
        }
        stripper = ThinkStripper()
        try:
            with httpx.stream("POST", self._url("/api/chat"), json=payload,
                              timeout=self.timeout) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        raise LLMError(self.friendly(RuntimeError(data["error"])))
                    piece = (data.get("message") or {}).get("content", "")
                    if piece:
                        visible = stripper.feed(piece)
                        if visible:
                            yield visible
                    if data.get("done"):
                        break
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(self.friendly(exc)) from exc
        tail = stripper.flush()
        if tail:
            yield tail

    # -------------------------------------------------------------- embeddings
    def embed(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            try:
                resp = httpx.post(
                    self._url("/api/embed"),
                    json={"model": self.embed_model, "input": batch},
                    timeout=max(self.timeout, 120),
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                raise LLMError(
                    self.friendly(exc)
                    + f" (embedding model: {self.embed_model})"
                ) from exc
            vectors = data.get("embeddings")
            if not vectors:
                raise LLMError("Ollama returned no embeddings. Check the embedding model name in Settings.")
            out.extend(vectors)
        return out

    # ------------------------------------------------------------------ status
    def health(self, timeout: float = 4.0) -> dict:
        started = time.time()
        try:
            resp = httpx.get(self._url("/api/tags"), timeout=timeout)
            resp.raise_for_status()
            names = [m.get("name", "") for m in resp.json().get("models", [])]
            ms = int((time.time() - started) * 1000)
            return {
                "ok": True,
                "models": names,
                "has_model": self.model in names or f"{self.model}:latest" in names,
                "has_embed": self.embed_model in names,
                "latency_ms": ms,
                "endpoint": self.base,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": self.friendly(exc), "endpoint": self.base,
                    "models": [], "has_model": False, "has_embed": False}

    def context_length(self) -> int:
        """Read num_ctx back from Ollama so doctor can prove it was applied."""
        try:
            resp = httpx.post(self._url("/api/show"), json={"model": self.model}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            params = data.get("parameters") or ""
            match = re.search(r"num_ctx\s+(\d+)", params)
            if match:
                return int(match.group(1))
            info = data.get("model_info") or {}
            for key, value in info.items():
                if key.endswith("context_length"):
                    return int(value)
        except Exception:  # noqa: BLE001
            pass
        return 0
