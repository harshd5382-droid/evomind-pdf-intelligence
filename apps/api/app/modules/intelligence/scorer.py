"""Intelligence Score — composite measure of how much the system has actually learned."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func

from app.db import postgres
from app.db.models import (
    Answer,
    Chunk,
    Contradiction,
    Document,
    Hypothesis,
    Insight,
    Memory,
    Metric,
    Question,
)


def _safe_avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_score() -> dict:
    """Combine concept count, solved questions, gap reduction, hypotheses, confidence trend."""
    with postgres.session_scope() as s:
        n_docs = s.query(func.count(Document.id)).scalar() or 0
        n_chunks = s.query(func.count(Chunk.id)).scalar() or 0
        n_questions = s.query(func.count(Question.id)).scalar() or 0
        n_answered = s.query(func.count(Question.id)).filter(Question.status == "answered").scalar() or 0
        n_unresolved = s.query(func.count(Question.id)).filter(Question.status == "unresolved").scalar() or 0
        n_insights = s.query(func.count(Insight.id)).scalar() or 0
        n_concepts = s.query(func.count(Memory.id)).filter(Memory.layer == "semantic").scalar() or 0
        n_hyp = s.query(func.count(Hypothesis.id)).scalar() or 0
        n_contradictions = s.query(func.count(Contradiction.id)).scalar() or 0

        recent_confs = [
            float(c) for (c,) in s.query(Answer.confidence).order_by(Answer.created_at.desc()).limit(50).all()
        ]
        avg_confidence = _safe_avg(recent_confs)

    # Heuristic composite score
    score = (
        n_concepts * 1.5
        + n_answered * 2.0
        + n_insights * 4.0
        + n_hyp * 5.0
        + n_contradictions * 3.0
        - n_unresolved * 0.5
        + avg_confidence * 30.0
    )
    score = max(0.0, score)

    snapshot = {
        "score": round(score, 2),
        "documents": n_docs,
        "chunks": n_chunks,
        "questions": n_questions,
        "answered": n_answered,
        "unresolved": n_unresolved,
        "insights": n_insights,
        "concepts": n_concepts,
        "hypotheses": n_hyp,
        "contradictions": n_contradictions,
        "avg_confidence": round(avg_confidence, 3),
    }

    with postgres.session_scope() as s:
        s.add(Metric(name="intelligence_score", value=snapshot["score"], extra=snapshot))
    return snapshot


def score_history(days: int = 14) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    with postgres.session_scope() as s:
        rows = (
            s.query(Metric)
            .filter(Metric.name == "intelligence_score", Metric.created_at >= cutoff)
            .order_by(Metric.created_at.asc())
            .all()
        )
    return [
        {"t": r.created_at.isoformat(), "value": r.value, "extra": r.extra or {}}
        for r in rows
    ]
