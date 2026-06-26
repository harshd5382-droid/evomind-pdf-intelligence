"""Tests for the eval framework (LLM judge mocked) + feedback."""
from __future__ import annotations

import pytest
from app.db import postgres
from app.db.models import Answer, Feedback, Question
from app.modules.eval import engine


@pytest.fixture
def answered_with_citations(clean_db):
    with postgres.session_scope() as s:
        q = Question(id="q-e", text="What is X?", category="understanding", status="answered")
        s.add(q)
        s.flush()
        s.add(Answer(
            question_id=q.id, text="X is Y.", confidence=0.9,
            citations=[{"document_id": "d1", "title": "Doc", "page": 1, "snippet": "X is Y"}],
        ))


def test_run_eval_aggregates_judge_scores(answered_with_citations, monkeypatch):
    monkeypatch.setattr(engine.llm, "complete_json", lambda *a, **k: {
        "grounded": True, "score": 0.8, "reason": "supported",
    })
    out = engine.run_eval(sample_size=10)
    assert out["faithfulness"] == 0.8
    assert out["grounded_rate"] == 1.0
    assert out["citation_coverage"] == 1.0
    assert out["sample_size"] == 1


def test_run_eval_empty_corpus(clean_db):
    out = engine.run_eval(sample_size=10)
    assert out["faithfulness"] == 0.0
    assert out["sample_size"] == 0


def test_eval_history_returns_snapshots(answered_with_citations, monkeypatch):
    monkeypatch.setattr(engine.llm, "complete_json", lambda *a, **k: {"grounded": True, "score": 0.5})
    engine.run_eval(sample_size=5)
    hist = engine.eval_history(days=30)
    assert len(hist) == 1
    assert hist[0]["value"] == 0.5


# --- feedback ---------------------------------------------------------------

def test_feedback_roundtrip(client, clean_db):
    res = client.post("/api/feedback", json={
        "target_kind": "chat_message", "target_id": "m-1", "rating": 1,
    })
    assert res.status_code == 200

    client.post("/api/feedback", json={"target_kind": "answer", "target_id": "a-1", "rating": -1})

    summary = client.get("/api/feedback/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["up"] == 1 and body["down"] == 1
    assert body["approval_rate"] == 0.5

    with postgres.session_scope() as s:
        assert s.query(Feedback).count() == 2


def test_feedback_rejects_bad_kind(client, clean_db):
    res = client.post("/api/feedback", json={
        "target_kind": "bogus", "target_id": "x", "rating": 1,
    })
    assert res.status_code == 422


def test_eval_run_endpoint(client, answered_with_citations, monkeypatch):
    monkeypatch.setattr(engine.llm, "complete_json", lambda *a, **k: {"grounded": True, "score": 1.0})
    res = client.post("/api/eval/run", json={"sample_size": 5})
    assert res.status_code == 200
    assert res.json()["faithfulness"] == 1.0
    assert client.get("/api/eval/history").status_code == 200
