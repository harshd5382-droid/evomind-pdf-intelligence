"""Grounded chat ("Ask EvoMind").

Exposes the existing hybrid retrieval + grounded-answering stack as a multi-turn
conversational surface. This intentionally reuses `hybrid_search` and the same
citation shape as the autopilot solver — it does NOT reimplement retrieval.
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger

from app.db import postgres, redis_client
from app.db.models import ChatMessage, Conversation
from app.llm import router as llm
from app.llm.prompts import CHAT_SYSTEM, CHAT_USER
from app.llm.router import purpose
from app.modules.retrieval.hybrid import Hit, hybrid_search

# How many prior turns to feed back as conversational context.
_HISTORY_TURNS = 6


def _format_evidence(hits: list[Hit]) -> tuple[str, list[dict]]:
    """Same evidence/citation shape the solver uses, so the frontend can render
    chat citations identically to answer citations."""
    lines = []
    citations = []
    for i, h in enumerate(hits):
        snippet = (h.text or "")[:500]
        lines.append(f"[#{i}] {h.title} p.{h.page}: {snippet}")
        citations.append({
            "index": i,
            "chunk_id": h.chunk_id,
            "document_id": h.document_id,
            "title": h.title,
            "page": h.page,
            "section": h.section,
            "kind": h.kind,
            "snippet": snippet[:280],
            "score": h.fused_score,
        })
    return "\n\n".join(lines) or "(no evidence found)", citations


def _history_text(messages: list[ChatMessage]) -> str:
    if not messages:
        return "(start of conversation)"
    recent = messages[-_HISTORY_TURNS:]
    return "\n".join(f"{m.role.capitalize()}: {m.content}" for m in recent)


def _title_from(message: str) -> str:
    t = " ".join(message.strip().split())
    return (t[:60] + "…") if len(t) > 60 else (t or "New conversation")


def answer_chat(message: str, conversation_id: str | None = None, *, top_k: int = 8) -> dict:
    """Answer one user turn. Creates the conversation if needed, persists both
    the user message and the grounded assistant reply, and returns the reply."""
    message = (message or "").strip()
    if not message:
        raise ValueError("message must not be empty")

    # --- Resolve / create the conversation, capture prior turns for context ---
    with postgres.session_scope() as s:
        if conversation_id:
            conv = s.get(Conversation, conversation_id)
            if conv is None:
                raise ValueError(f"conversation {conversation_id} not found")
        else:
            conv = Conversation(title=_title_from(message))
            s.add(conv)
            s.flush()
        conversation_id = conv.id
        prior = list(conv.messages)
        history = _history_text(prior)
        s.add(ChatMessage(conversation_id=conversation_id, role="user", content=message))

    # --- Retrieve evidence (corpus-wide) and answer, grounded ---
    hits = hybrid_search(message, top_k=top_k)
    evidence_str, citations = _format_evidence(hits)

    with purpose("chat"):
        out = llm.complete_json(
            CHAT_SYSTEM,
            CHAT_USER.format(history=history, message=message, evidence=evidence_str),
            temperature=0.3, max_tokens=1200,
        )
    if not isinstance(out, dict):
        out = {}

    answer_text = str(out.get("answer", "")).strip() or "(no answer produced)"
    try:
        confidence = float(out.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    used_idx = out.get("citations") or []
    used_citations = [citations[i] for i in used_idx if isinstance(i, int) and 0 <= i < len(citations)]

    # --- Persist the assistant turn + bump conversation timestamp ---
    with postgres.session_scope() as s:
        msg = ChatMessage(
            conversation_id=conversation_id, role="assistant",
            content=answer_text, citations=used_citations, confidence=confidence,
        )
        s.add(msg)
        conv = s.get(Conversation, conversation_id)
        if conv is not None:
            conv.updated_at = datetime.utcnow()
        s.flush()
        msg_id = msg.id

    try:
        redis_client.publish_event({
            "type": "chat.replied", "conversation_id": conversation_id,
            "message_id": msg_id, "confidence": confidence,
            "preview": answer_text[:200],
        })
    except Exception as e:
        logger.debug("chat event publish skipped: {}", e)

    return {
        "conversation_id": conversation_id,
        "message_id": msg_id,
        "answer": answer_text,
        "confidence": confidence,
        "citations": used_citations,
    }
