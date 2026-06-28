"""Shared slowapi rate limiter.

Keyed on client IP. Storage is in-memory by default; if a Redis URL is set the
limiter uses it so limits hold across multiple API workers. Mirrors the app's
general "degrade gracefully without infra" stance — no Redis just means
per-process limits.
"""
from __future__ import annotations

from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

_settings = get_settings()


def _storage_uri() -> str | None:
    url = (_settings.redis_url or "").strip()
    # The in-memory pubsub/test mode uses "memory://" — not a real Redis.
    if url.startswith("redis://") or url.startswith("rediss://"):
        return url
    return None


_uri = _storage_uri()
if _uri:
    logger.info("Rate limiter using Redis storage")

limiter = Limiter(
    key_func=get_remote_address,
    enabled=_settings.rate_limit_enabled,
    default_limits=[_settings.rate_limit_default],
    storage_uri=_uri,
)
