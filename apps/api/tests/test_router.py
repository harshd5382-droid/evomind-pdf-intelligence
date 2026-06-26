"""Unit tests for the LLM router's 429-aware fallback state machine.

These exercise the most intricate untested logic in the backend without
touching any real provider — fake providers are injected via monkeypatch.
"""
from __future__ import annotations

import time

import pytest
from app.llm import router
from app.llm.base import LLMResult


class _FakeProvider:
    def __init__(self, name, *, raise_exc=None, text="ok"):
        self.name = name
        self._raise = raise_exc
        self._text = text
        self.calls = 0

    def complete(self, system, user, **kwargs):
        self.calls += 1
        if self._raise is not None:
            raise self._raise
        return LLMResult(text=self._text, model=f"{self.name}-model", usage={"input": 1, "output": 1})


class _RateLimit(Exception):
    """Carries a 429 status_code, like provider SDK errors do."""
    status_code = 429


@pytest.fixture(autouse=True)
def _reset_router_state():
    """Each test starts from a clean fallback state."""
    with router._fallback_lock:
        router._fallback_state.update(
            primary_429s=[], cooldown_until=0.0, trips=0,
            last_health_check=0.0, fallback_healthy=True, fallback_health_msg="",
        )
    yield


# --- _is_rate_limit_error detection -----------------------------------------

@pytest.mark.parametrize("exc", [
    RuntimeError("Error code: 429 Too Many Requests"),
    _RateLimit("rate limited"),
    type("RateLimitError", (Exception,), {})("boom"),
])
def test_detects_rate_limit_errors(exc):
    assert router._is_rate_limit_error(exc) is True


def test_non_rate_limit_error_not_flagged():
    assert router._is_rate_limit_error(ValueError("prompt too long")) is False


# --- fallback on 429 --------------------------------------------------------

def test_429_falls_back_to_secondary(monkeypatch):
    primary = _FakeProvider("nvidia", raise_exc=_RateLimit())
    fallback = _FakeProvider("ollama", text="fallback answer")

    def fake_chat_provider(name):
        return primary if name == "nvidia" else fallback

    monkeypatch.setattr(router, "chat_provider", fake_chat_provider)
    monkeypatch.setattr(router, "_check_fallback_health", lambda: (True, "ok"))
    monkeypatch.setattr(router.get_settings(), "primary_provider", "nvidia")
    monkeypatch.setattr(router.get_settings(), "fallback_provider", "ollama")

    res, used = router._call_with_fallback("sys", "user")

    assert used == "ollama"
    assert res.text == "fallback answer"
    assert primary.calls == 1 and fallback.calls == 1


def test_non_429_error_propagates_without_fallback(monkeypatch):
    primary = _FakeProvider("nvidia", raise_exc=ValueError("bad prompt"))
    fallback = _FakeProvider("ollama")
    monkeypatch.setattr(router, "chat_provider", lambda name: primary if name == "nvidia" else fallback)
    monkeypatch.setattr(router, "_check_fallback_health", lambda: (True, "ok"))
    monkeypatch.setattr(router.get_settings(), "primary_provider", "nvidia")
    monkeypatch.setattr(router.get_settings(), "fallback_provider", "ollama")

    with pytest.raises(ValueError):
        router._call_with_fallback("sys", "user")
    assert fallback.calls == 0  # fallback must NOT be burned on real errors


def test_repeated_429s_trip_cooldown(monkeypatch):
    s = router.get_settings()
    monkeypatch.setattr(s, "fallback_provider", "ollama")
    threshold = int(s.fallback_429_threshold)

    for _ in range(threshold):
        router._record_primary_429()

    with router._fallback_lock:
        assert router._fallback_state["trips"] == 1
        assert router._fallback_state["cooldown_until"] > time.time()


def test_fallback_status_reports_cooldown(monkeypatch):
    s = router.get_settings()
    monkeypatch.setattr(s, "fallback_provider", "ollama")
    monkeypatch.setattr(router, "_check_fallback_health", lambda: (True, "ok"))
    for _ in range(int(s.fallback_429_threshold)):
        router._record_primary_429()

    st = router.fallback_status()
    assert st["in_cooldown"] is True
    assert st["active"] == "ollama"
    assert st["cooldown_remaining_sec"] > 0
