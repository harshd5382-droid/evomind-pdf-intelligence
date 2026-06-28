"""Tests for grounded chat — engine multi-turn behaviour + HTTP surface,
with retrieval and the LLM mocked."""
from __future__ import annotations

import pytest
from app.db import postgres
from app.db.models import ChatMessage, Conversation
from app.modules.chat import engine
from app.modules.retrieval.hybrid import Hit


def _hit(i: int) -> Hit:
    return Hit(
        chunk_id=f"c-{i}", document_id="doc-1", page=i + 1, title="Doc 1",
        section=None, kind="text", text=f"fact {i}", fused_score=0.5,
    )


@pytest.fixture
def mocked_retrieval(monkeypatch):
    monkeypatch.setattr(engine, "hybrid_search", lambda *a, **k: [_hit(0), _hit(1)])
    monkeypatch.setattr(engine.llm, "complete_json", lambda *a, **k: {
        "answer": "Grounded reply.", "confidence": 0.82, "citations": [0],
    })


def test_chat_creates_conversation_and_persists_turns(clean_db, mocked_retrieval):
    out = engine.answer_chat("What is in doc 1?")

    assert out["answer"] == "Grounded reply."
    assert out["confidence"] == 0.82
    assert len(out["citations"]) == 1
    assert out["citations"][0]["chunk_id"] == "c-0"

    with postgres.session_scope() as s:
        conv = s.get(Conversation, out["conversation_id"])
        assert conv is not None
        msgs = s.query(ChatMessage).filter(
            ChatMessage.conversation_id == conv.id
        ).order_by(ChatMessage.created_at).all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert msgs[1].citations[0]["chunk_id"] == "c-0"


def test_chat_continues_existing_conversation(clean_db, mocked_retrieval):
    first = engine.answer_chat("First question?")
    second = engine.answer_chat("Follow up?", conversation_id=first["conversation_id"])

    assert second["conversation_id"] == first["conversation_id"]
    with postgres.session_scope() as s:
        msgs = s.query(ChatMessage).filter(
            ChatMessage.conversation_id == first["conversation_id"]
        ).all()
        assert len(msgs) == 4  # 2 user + 2 assistant


def test_chat_empty_message_raises(clean_db):
    with pytest.raises(ValueError):
        engine.answer_chat("   ")


def test_chat_unknown_conversation_raises(clean_db, mocked_retrieval):
    with pytest.raises(ValueError):
        engine.answer_chat("hi", conversation_id="nope")


# --- HTTP surface -----------------------------------------------------------

def test_chat_endpoint_roundtrip(client, clean_db, mocked_retrieval):
    res = client.post("/api/chat", json={"message": "Tell me about doc 1"})
    assert res.status_code == 200
    body = res.json()
    cid = body["conversation_id"]
    assert body["answer"] == "Grounded reply."

    listed = client.get("/api/chat/conversations")
    assert listed.status_code == 200
    assert any(c["id"] == cid for c in listed.json())

    msgs = client.get(f"/api/chat/conversations/{cid}")
    assert msgs.status_code == 200
    assert [m["role"] for m in msgs.json()] == ["user", "assistant"]


def test_chat_endpoint_rejects_empty_message(client, clean_db):
    # Empty string fails schema validation (min_length=1) → 422.
    res = client.post("/api/chat", json={"message": ""})
    assert res.status_code == 422
    # Whitespace-only passes the schema but is rejected by the handler → 400.
    res = client.post("/api/chat", json={"message": "   "})
    assert res.status_code == 400


def test_conversation_messages_404_for_unknown(client, clean_db):
    res = client.get("/api/chat/conversations/does-not-exist")
    assert res.status_code == 404
