"""Lightweight pubsub + ring buffer used by the SSE research feed.

If REDIS_URL is reachable, uses redis. Otherwise falls back to an in-process
implementation that supports just the methods we use: lpush, ltrim, lrange,
publish, pubsub.get_message.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

from loguru import logger

from app.core.config import get_settings

_settings = get_settings()
_real = None  # type: ignore[var-annotated]
_memory: _MemoryRedis | None = None


class _MemoryPubSub:
    def __init__(self, broker: _MemoryRedis, channel: str) -> None:
        self._broker = broker
        self._channel = channel
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        broker._subscribe(channel, self)

    def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0) -> dict | None:
        end = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                if self._queue:
                    data = self._queue.popleft()
                    return {"type": "message", "channel": self._channel, "data": data}
            if time.monotonic() >= end:
                return None
            time.sleep(0.05)

    def deliver(self, data: str) -> None:
        with self._lock:
            self._queue.append(data)

    def unsubscribe(self, *_args, **_kwargs) -> None:
        self._broker._unsubscribe(self._channel, self)

    def close(self) -> None:
        self.unsubscribe()


class _MemoryRedis:
    """Thread-safe in-memory replacement for the few redis ops we use."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._lists: dict[str, deque[str]] = {}
        self._subs: dict[str, list[_MemoryPubSub]] = {}

    # list ops
    def lpush(self, key: str, value: str) -> int:
        with self._lock:
            d = self._lists.setdefault(key, deque())
            d.appendleft(value)
            return len(d)

    def ltrim(self, key: str, start: int, end: int) -> bool:
        with self._lock:
            d = self._lists.get(key)
            if not d:
                return True
            items = list(d)
            # redis end is inclusive
            trimmed = items[start : end + 1]
            self._lists[key] = deque(trimmed)
            return True

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        with self._lock:
            d = self._lists.get(key)
            if not d:
                return []
            items = list(d)
            if end == -1:
                return items[start:]
            return items[start : end + 1]

    # pubsub ops
    def publish(self, channel: str, message: str) -> int:
        with self._lock:
            subs = list(self._subs.get(channel, ()))
        for sub in subs:
            sub.deliver(message)
        return len(subs)

    def pubsub(self):
        broker = self
        class _Factory:
            def __init__(self):
                self._channel: str | None = None
                self._sub: _MemoryPubSub | None = None
            def subscribe(self, channel: str) -> None:
                self._channel = channel
                self._sub = _MemoryPubSub(broker, channel)
            def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0):
                if self._sub is None:
                    return None
                return self._sub.get_message(ignore_subscribe_messages, timeout)
            def unsubscribe(self, *_args, **_kwargs) -> None:
                if self._sub:
                    self._sub.unsubscribe()
            def close(self) -> None:
                self.unsubscribe()
        return _Factory()

    # internal
    def _subscribe(self, channel: str, sub: _MemoryPubSub) -> None:
        with self._lock:
            self._subs.setdefault(channel, []).append(sub)

    def _unsubscribe(self, channel: str, sub: _MemoryPubSub) -> None:
        with self._lock:
            arr = self._subs.get(channel, [])
            if sub in arr:
                arr.remove(sub)


def _is_memory_url(url: str) -> bool:
    return not url or url.startswith("memory://")


def client():
    """Return either the live redis client or our in-memory shim — both speak the
    methods used in this module."""
    global _real, _memory
    if _real is not None:
        return _real
    if _memory is not None:
        return _memory

    if _is_memory_url(_settings.redis_url):
        _memory = _MemoryRedis()
        logger.info("Redis: in-memory mode (REDIS_URL={!r})", _settings.redis_url)
        return _memory

    try:
        import redis as _redis_pkg
        c = _redis_pkg.Redis.from_url(_settings.redis_url, decode_responses=True, socket_connect_timeout=1.5)
        c.ping()
        _real = c
        return _real
    except Exception as e:
        logger.warning("Redis unreachable ({}); using in-memory feed/pubsub", e)
        _memory = _MemoryRedis()
        return _memory


FEED_KEY = "evomind:feed"
FEED_MAX = 500


def publish_event(event: dict[str, Any]) -> None:
    c = client()
    payload = json.dumps(event)
    c.lpush(FEED_KEY, payload)
    c.ltrim(FEED_KEY, 0, FEED_MAX - 1)
    c.publish(FEED_KEY, payload)


def recent_events(limit: int = 50) -> list[dict]:
    raw = client().lrange(FEED_KEY, 0, limit - 1)
    out = []
    for r in raw:
        try:
            out.append(json.loads(r))
        except Exception:
            continue
    return out


def mode() -> str:
    c = client()
    return "memory" if isinstance(c, _MemoryRedis) else "redis"


def status() -> dict:
    c = client()
    if isinstance(c, _MemoryRedis):
        return {"mode": "memory", "reachable": True, "error": None}
    try:
        c.ping()
        return {"mode": "redis", "reachable": True, "error": None}
    except Exception as exc:
        return {"mode": "redis", "reachable": False, "error": str(exc)}
