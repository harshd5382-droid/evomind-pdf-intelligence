"""Unit tests for the composite intelligence score (pure heuristic)."""
from __future__ import annotations

from app.db import postgres
from app.db.models import (
    Answer,
    Contradiction,
    Hypothesis,
    Insight,
    Memory,
    Metric,
    Question,
)
from app.modules.intelligence.scorer import compute_score, score_history


def _seed_known_corpus():
    with postgres.session_scope() as s:
        # 1 semantic memory == 1 concept (×1.5)
        s.add(Memory(layer="semantic", content="a concept", importance=0.5))
        # 1 answered question (×2.0) + the answer (confidence feeds avg_confidence)
        q = Question(text="answered q", category="understanding", status="answered")
        s.add(q)
        s.flush()
        s.add(Answer(question_id=q.id, text="ans", confidence=0.8))
        # 1 unresolved question (×-0.5)
        s.add(Question(text="open q", category="understanding", status="unresolved"))
        s.add(Insight(title="i", body="b", kind="synthesis"))      # ×4.0
        s.add(Hypothesis(statement="h", rationale="r"))            # ×5.0
        s.add(Contradiction(summary="c", severity=0.5))           # ×3.0


def test_compute_score_matches_heuristic(clean_db):
    _seed_known_corpus()
    snap = compute_score()

    # 1*1.5 + 1*2.0 + 1*4.0 + 1*5.0 + 1*3.0 - 1*0.5 + 0.8*30 = 39.0
    assert snap["score"] == 39.0
    assert snap["concepts"] == 1
    assert snap["answered"] == 1
    assert snap["unresolved"] == 1
    assert snap["insights"] == 1
    assert snap["hypotheses"] == 1
    assert snap["contradictions"] == 1
    assert snap["avg_confidence"] == 0.8


def test_compute_score_empty_corpus_is_zero(clean_db):
    snap = compute_score()
    assert snap["score"] == 0.0
    assert snap["documents"] == 0
    assert snap["avg_confidence"] == 0.0


def test_compute_score_persists_metric_row(clean_db):
    compute_score()
    with postgres.session_scope() as s:
        rows = s.query(Metric).filter(Metric.name == "intelligence_score").all()
        assert len(rows) == 1
        assert rows[0].extra  # snapshot stored in the JSON column


def test_score_history_returns_persisted_snapshots(clean_db):
    compute_score()
    compute_score()
    hist = score_history(days=14)
    assert len(hist) == 2
    assert all("value" in h and "t" in h for h in hist)
