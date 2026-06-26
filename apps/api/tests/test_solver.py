"""Unit tests for the grounded solver — citation wiring + confidence/status,
with retrieval and the LLM mocked out."""
from __future__ import annotations

import pytest
from app.db import postgres
from app.db.models import Answer, Document, Question
from app.modules.retrieval.hybrid import Hit
from app.modules.solver import engine


def _make_hit(i: int) -> Hit:
    return Hit(
        chunk_id=f"chunk-{i}", document_id="doc-x", page=i + 1,
        title="Doc X", section=None, kind="text",
        text=f"evidence snippet {i}", vector_score=0.9, vector_rank=1, fused_score=0.5,
    )


@pytest.fixture
def seeded_question(clean_db):
    with postgres.session_scope() as s:
        s.add(Document(id="doc-x", title="Doc X", filename="x.pdf", path="/x.pdf", status="ready"))
        s.add(Question(id="q-x", text="What is X?", category="understanding",
                       document_id="doc-x", status="open"))
    return "q-x"


def test_solver_wires_citations_and_marks_answered(seeded_question, monkeypatch):
    monkeypatch.setattr(engine, "hybrid_search", lambda *a, **k: [_make_hit(0), _make_hit(1)])
    monkeypatch.setattr(engine.llm, "complete_json", lambda *a, **k: {
        "answer": "X is the thing.", "reasoning": "because evidence #0",
        "confidence": 0.9, "citations": [0],
    })
    # keep memory recall deterministic / out of the way
    monkeypatch.setattr("app.modules.memory.search_memories", lambda *a, **k: [], raising=False)

    out = engine.solve_question("q-x")

    assert out["status"] == "answered"
    assert out["confidence"] == 0.9
    assert out["answer"] == "X is the thing."
    # only the cited hit (index 0) is attached
    assert len(out["citations"]) == 1
    assert out["citations"][0]["chunk_id"] == "chunk-0"

    with postgres.session_scope() as s:
        q = s.get(Question, "q-x")
        assert q.status == "answered"
        ans = s.query(Answer).filter(Answer.question_id == "q-x").one()
        assert ans.confidence == 0.9
        assert ans.citations[0]["chunk_id"] == "chunk-0"


def test_solver_low_confidence_marks_unresolved(seeded_question, monkeypatch):
    monkeypatch.setattr(engine, "hybrid_search", lambda *a, **k: [_make_hit(0)])
    monkeypatch.setattr(engine.llm, "complete_json", lambda *a, **k: {
        "answer": "maybe", "confidence": 0.1, "citations": [],
    })
    monkeypatch.setattr("app.modules.memory.search_memories", lambda *a, **k: [], raising=False)

    out = engine.solve_question("q-x")
    assert out["status"] == "unresolved"
    assert out["confidence"] == 0.1


def test_solver_no_evidence_returns_honest_no_answer(seeded_question, monkeypatch):
    monkeypatch.setattr(engine, "hybrid_search", lambda *a, **k: [])

    out = engine.solve_question("q-x")
    assert out["status"] == "unresolved"
    assert out["confidence"] == 0.0
    assert out["citations"] == []
    assert "no relevant evidence" in out["answer"].lower()


def test_solver_raises_on_missing_question(clean_db):
    with pytest.raises(ValueError):
        engine.solve_question("does-not-exist")
