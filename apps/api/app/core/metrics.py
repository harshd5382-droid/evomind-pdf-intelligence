"""Prometheus metrics for LLM usage and autopilot phases.

HTTP-level metrics (request count/latency by route) come from
prometheus-fastapi-instrumentator, wired in main.py. This module adds the
domain-specific series the instrumentator can't see: per-provider LLM latency
and token throughput, and per-phase autopilot timing.

All helpers are safe to call unconditionally — if prometheus_client isn't
installed they degrade to no-ops.
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

    _ENABLED = True
except Exception:  # pragma: no cover - prometheus_client is a declared dep
    _ENABLED = False


if _ENABLED:
    LLM_LATENCY = Histogram(
        "evomind_llm_latency_seconds",
        "LLM chat-completion latency",
        ["provider", "purpose"],
    )
    LLM_TOKENS = Counter(
        "evomind_llm_tokens_total",
        "LLM tokens processed",
        ["provider", "purpose", "direction"],  # direction: input|output
    )
    PHASE_LATENCY = Histogram(
        "evomind_autopilot_phase_seconds",
        "Autopilot phase duration",
        ["phase"],
    )


def record_llm(provider: str, purpose: str, latency_ms: int, input_tokens: int, output_tokens: int) -> None:
    if not _ENABLED:
        return
    try:
        LLM_LATENCY.labels(provider=provider, purpose=purpose).observe(latency_ms / 1000.0)
        if input_tokens:
            LLM_TOKENS.labels(provider=provider, purpose=purpose, direction="input").inc(input_tokens)
        if output_tokens:
            LLM_TOKENS.labels(provider=provider, purpose=purpose, direction="output").inc(output_tokens)
    except Exception:
        pass


def observe_phase(phase: str, seconds: float) -> None:
    if not _ENABLED:
        return
    try:
        PHASE_LATENCY.labels(phase=phase).observe(seconds)
    except Exception:
        pass
