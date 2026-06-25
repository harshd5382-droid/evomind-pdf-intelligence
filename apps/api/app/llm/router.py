"""LLM router with rate-limit-aware fallback.

The router serves three roles:

  1. Provider lookup by name (cached).
  2. Usage attribution via the `purpose` context manager — every call records
     a Usage row tagged with which subsystem (solver / questioner / journal /
     ...) made it.
  3. **Automatic fallback** — when the primary provider returns persistent
     429s (free-tier rate limiting), the router auto-switches to a local
     fallback (Ollama) for a configurable cooldown, then probes primary
     again. This means the autopilot never stalls completely; it just slows
     down during throttle windows. After the cooldown, primary takes over
     again.

The fallback state is tracked in module-level globals guarded by a lock,
so all of the autopilot threads see consistent routing decisions.
"""
from __future__ import annotations

import json
import re
import threading
import time
from contextvars import ContextVar
from functools import lru_cache
from typing import Optional

from loguru import logger

from app.core.config import get_settings
from app.llm.base import LLMProvider, EmbeddingProvider, LLMResult


# ---------------------------------------------------------------------------
# Purpose attribution
# ---------------------------------------------------------------------------

_purpose_var: ContextVar[str] = ContextVar("evomind_llm_purpose", default="general")


class purpose:
    """Context manager: with purpose("solver"): llm.complete(...)"""

    def __init__(self, name: str) -> None:
        self.name = name
        self._token = None

    def __enter__(self) -> "purpose":
        self._token = _purpose_var.set(self.name)
        return self

    def __exit__(self, *exc) -> None:
        if self._token is not None:
            _purpose_var.reset(self._token)


# ---------------------------------------------------------------------------
# Provider factories (cached singletons)
# ---------------------------------------------------------------------------

@lru_cache
def chat_provider(name: str | None = None) -> LLMProvider:
    s = get_settings()
    name = (name or s.primary_provider).lower()
    if name == "nvidia":
        from app.llm.providers.nvidia_p import NvidiaProvider
        return NvidiaProvider()
    if name == "anthropic":
        from app.llm.providers.anthropic_p import AnthropicProvider
        return AnthropicProvider()
    if name == "openai":
        from app.llm.providers.openai_p import OpenAIProvider
        return OpenAIProvider()
    if name == "gemini":
        from app.llm.providers.gemini_p import GeminiProvider
        return GeminiProvider()
    if name == "ollama":
        from app.llm.providers.ollama_p import OllamaProvider
        return OllamaProvider()
    if name == "groq":
        from app.llm.providers.groq_p import GroqProvider
        return GroqProvider()
    raise ValueError(f"Unknown provider: {name}")


@lru_cache
def embedding_provider(name: str | None = None) -> EmbeddingProvider:
    s = get_settings()
    name = (name or s.embedding_provider).lower()
    if name == "nvidia":
        from app.llm.providers.nvidia_p import NvidiaEmbeddings
        return NvidiaEmbeddings()
    if name == "openai":
        from app.llm.providers.openai_p import OpenAIEmbeddings
        return OpenAIEmbeddings()
    from app.llm.providers.local_embeddings import LocalEmbeddings
    return LocalEmbeddings()


# ---------------------------------------------------------------------------
# Fallback state machine
# ---------------------------------------------------------------------------

_fallback_lock = threading.Lock()
_fallback_state: dict = {
    "primary_429s": [],          # list of timestamps in the last 60 s
    "cooldown_until": 0.0,       # if time.time() < this, use fallback
    "trips": 0,                  # how many times we've fallen back this process
    "last_health_check": 0.0,    # when we last probed fallback availability
    "fallback_healthy": True,    # cached result
    "fallback_health_msg": "",
}


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Heuristic: did this exception come from a 429 response?

    Different providers raise different exception classes (openai.RateLimitError,
    plain RuntimeError with "429" in message, httpx.HTTPStatusError, ...).
    We match on both the type's __name__ and the error message body.
    """
    msg = str(exc) or ""
    if "429" in msg or "Too Many Requests" in msg:
        return True
    cls = type(exc).__name__
    if cls == "RateLimitError":
        return True
    # openai.APIStatusError with .status_code
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    # httpx.HTTPStatusError exposes .response
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 429:
        return True
    return False


def _record_primary_429() -> None:
    """A primary call just hit 429 (after the SDK's own retries). Track it,
    and if we've crossed the threshold, trip the cooldown."""
    s = get_settings()
    if not s.fallback_provider:
        return
    now = time.time()
    with _fallback_lock:
        recent = [t for t in _fallback_state["primary_429s"] if now - t < 60.0]
        recent.append(now)
        _fallback_state["primary_429s"] = recent
        if len(recent) >= int(s.fallback_429_threshold):
            until = now + float(s.fallback_cooldown_sec)
            if _fallback_state["cooldown_until"] < until:
                _fallback_state["cooldown_until"] = until
                _fallback_state["trips"] += 1
                logger.warning(
                    "router: primary throttled ({} 429s in 60s) — falling back to '{}' for {}s",
                    len(recent), s.fallback_provider, s.fallback_cooldown_sec,
                )


def _check_fallback_health() -> tuple[bool, str]:
    """Cheap liveness probe of the fallback provider, cached for a few seconds."""
    s = get_settings()
    now = time.time()
    with _fallback_lock:
        last = _fallback_state["last_health_check"]
        if now - last < int(s.fallback_min_health_check_sec):
            return (_fallback_state["fallback_healthy"], _fallback_state["fallback_health_msg"])

    healthy, msg = (False, "no fallback configured")
    if s.fallback_provider:
        try:
            if s.fallback_provider.lower() == "ollama":
                from app.llm.providers.ollama_p import health_check
                healthy, msg = health_check()
            else:
                healthy, msg = (True, "non-ollama fallback assumed healthy")
        except Exception as e:
            healthy, msg = (False, f"health check failed: {e}")

    with _fallback_lock:
        _fallback_state["last_health_check"] = time.time()
        _fallback_state["fallback_healthy"] = healthy
        _fallback_state["fallback_health_msg"] = msg
    return (healthy, msg)


def _active_provider() -> tuple[LLMProvider, str]:
    """Return (provider, name) — the one to use right now.

    Returns the fallback if (a) primary is in cooldown AND (b) fallback is
    healthy. Otherwise primary, even if fallback is healthier — primary is
    still our first-choice quality-wise."""
    s = get_settings()
    primary = s.primary_provider.lower()
    if not s.fallback_provider:
        return chat_provider(primary), primary
    now = time.time()
    with _fallback_lock:
        in_cooldown = now < _fallback_state["cooldown_until"]
    if in_cooldown:
        healthy, _ = _check_fallback_health()
        if healthy:
            return chat_provider(s.fallback_provider.lower()), s.fallback_provider.lower()
        # Fallback is also dead — back to primary, accept the 429s
        return chat_provider(primary), primary
    return chat_provider(primary), primary


def fallback_status() -> dict:
    """Public introspection — what is the router doing right now?"""
    s = get_settings()
    now = time.time()
    with _fallback_lock:
        cooldown_until = _fallback_state["cooldown_until"]
        trips = _fallback_state["trips"]
        recent_429s = [t for t in _fallback_state["primary_429s"] if now - t < 60.0]
    healthy, msg = _check_fallback_health()
    in_cooldown = now < cooldown_until
    active_name = s.fallback_provider if (in_cooldown and healthy) else s.primary_provider
    return {
        "primary": s.primary_provider,
        "fallback": s.fallback_provider or None,
        "active": active_name,
        "in_cooldown": in_cooldown,
        "cooldown_remaining_sec": max(0.0, cooldown_until - now),
        "primary_429s_in_last_60s": len(recent_429s),
        "trips_this_process": trips,
        "fallback_healthy": healthy,
        "fallback_health_msg": msg,
        "primary_model": getattr(s, f"{s.primary_provider}_model", "?"),
        "fallback_model": s.ollama_model if s.fallback_provider == "ollama" else "?",
    }


# ---------------------------------------------------------------------------
# Usage recording
# ---------------------------------------------------------------------------

def _record_usage(res: LLMResult, latency_ms: int, provider_name: str) -> None:
    try:
        from app.db import postgres
        from app.db.models import Usage
        u = res.usage or {}
        in_tok = int(u.get("input") or u.get("input_tokens") or u.get("prompt_tokens") or 0)
        out_tok = int(u.get("output") or u.get("output_tokens") or u.get("completion_tokens") or 0)
        with postgres.session_scope() as s:
            s.add(Usage(
                provider=provider_name,
                model=res.model,
                purpose=_purpose_var.get(),
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=latency_ms,
            ))
    except Exception as e:
        logger.debug("usage recording skipped: {}", e)


# ---------------------------------------------------------------------------
# Core call wrappers
# ---------------------------------------------------------------------------

def _call_with_fallback(system: str, user: str, **kwargs) -> tuple[LLMResult, str]:
    """Run a chat completion. Try the active provider. If primary returns 429,
    record it (which may trip the cooldown), and retry once on the fallback
    (if healthy and configured). Returns (result, provider_name_used)."""
    provider, name = _active_provider()
    t0 = time.monotonic()
    try:
        res = provider.complete(system, user, **kwargs)
        _record_usage(res, int((time.monotonic() - t0) * 1000), name)
        return (res, name)
    except Exception as e:
        s = get_settings()
        # If we were already on fallback, just propagate.
        if name != s.primary_provider.lower():
            raise
        # If this isn't a rate-limit error, propagate (don't burn the fallback
        # on real errors like prompt-too-long).
        if not _is_rate_limit_error(e):
            raise
        # Record + maybe trip cooldown
        _record_primary_429()
        # Try the fallback once for THIS call (regardless of cooldown — we
        # want the call to succeed if at all possible).
        if s.fallback_provider:
            healthy, _ = _check_fallback_health()
            if healthy:
                logger.info("router: primary 429 — retrying this call on fallback '{}'", s.fallback_provider)
                fb = chat_provider(s.fallback_provider.lower())
                t1 = time.monotonic()
                res = fb.complete(system, user, **kwargs)
                _record_usage(res, int((time.monotonic() - t1) * 1000), s.fallback_provider.lower())
                return (res, s.fallback_provider.lower())
        # No fallback or fallback unhealthy — reraise
        raise


def complete(system: str, user: str, **kwargs) -> LLMResult:
    res, _ = _call_with_fallback(system, user, **kwargs)
    return res


_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")
_JSON_ARR_RE = re.compile(r"\[[\s\S]*\]")


def complete_text(system: str, user: str, **kwargs) -> str:
    """Plain-text completion. Returns "" on failure rather than raising —
    callers tend to be optional cosmetic generators (narrative, journal)
    that should not crash the autopilot loop."""
    try:
        res, _ = _call_with_fallback(system, user, json_mode=False, **kwargs)
        return (res.text or "").strip()
    except Exception as e:
        logger.warning("complete_text failed: {}", e)
        return ""


def complete_json(system: str, user: str, **kwargs) -> dict | list:
    """JSON-mode completion. Tolerant to fences, prose, and top-level arrays."""
    try:
        res, _ = _call_with_fallback(system, user, json_mode=True, **kwargs)
    except Exception as e:
        logger.warning("complete_json failed: {}", e)
        return {}
    txt = (res.text or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:]
        txt = txt.strip()
    try:
        return json.loads(txt)
    except Exception:
        for rx in (_JSON_OBJ_RE, _JSON_ARR_RE):
            m = rx.search(txt)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    continue
        logger.warning("JSON parse failed; raw text: {}", txt[:300])
        return {}


# ---------------------------------------------------------------------------
# Embeddings — fallback NOT applied (dim mismatch would corrupt the index)
# ---------------------------------------------------------------------------

def embed(texts: list[str], *, kind: str = "passage") -> list[list[float]]:
    """Embed texts. Note: we do NOT fall back to local embeddings on rate-limit
    because doing so would silently produce vectors in a different vector
    space (different dim or just different semantics) which corrupts the
    retrieval index. If you want to switch embedding providers, set
    EMBEDDING_PROVIDER explicitly and reset the vector store."""
    if not texts:
        return []
    prov = embedding_provider()
    t0 = time.monotonic()
    vecs = prov.embed(texts, kind=kind)
    latency_ms = int((time.monotonic() - t0) * 1000)
    try:
        u = prov.usage() or {}
        in_tok = int(u.get("prompt_tokens") or u.get("input_tokens") or u.get("total_tokens") or 0)
        if in_tok or u:
            from app.db import postgres
            from app.db.models import Usage
            with postgres.session_scope() as s:
                s.add(Usage(
                    provider=prov.name,
                    model=getattr(get_settings(), f"{prov.name}_embedding_model", prov.name),
                    purpose=f"embed:{kind}",
                    input_tokens=in_tok,
                    output_tokens=0,
                    latency_ms=latency_ms,
                ))
    except Exception as e:
        logger.debug("embedding usage skipped: {}", e)
    return vecs
