"""Tests for the observability surface: /metrics endpoint, request-id header,
and the LLM metrics helper."""
from __future__ import annotations


def test_metrics_endpoint_exposes_prometheus(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    # Prometheus exposition format / our custom series should be present.
    body = res.text
    assert "evomind_llm" in body or "# HELP" in body


def test_request_id_header_is_returned(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID")


def test_request_id_is_propagated_when_supplied(client):
    res = client.get("/api/health", headers={"X-Request-ID": "trace-abc"})
    assert res.headers.get("X-Request-ID") == "trace-abc"


def test_record_llm_is_safe_to_call():
    from app.core import metrics
    # Should never raise regardless of prometheus availability.
    metrics.record_llm("nvidia", "solver", 1234, 100, 50)
    metrics.observe_phase("solve", 0.5)
