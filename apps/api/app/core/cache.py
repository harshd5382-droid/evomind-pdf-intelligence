"""Tiny in-process TTL cache.

Used to avoid recomputing hot, expensive read endpoints (e.g. the intelligence
metrics, which scan several tables) on every dashboard poll. In-process rather
than Redis so it works in the zero-infra path too; per-worker staleness up to
the TTL is acceptable for these read-only views.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from functools import wraps


def ttl_cache(seconds: float) -> Callable:
    def decorator(fn: Callable) -> Callable:
        lock = threading.Lock()
        store: dict = {}

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit is not None and now < hit[1]:
                    return hit[0]
            value = fn(*args, **kwargs)
            with lock:
                store[key] = (value, now + seconds)
            return value

        wrapper.cache_clear = store.clear  # type: ignore[attr-defined]
        return wrapper

    return decorator
