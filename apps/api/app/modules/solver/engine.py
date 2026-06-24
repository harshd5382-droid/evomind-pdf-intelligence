"""Autonomous solver — retrieves evidence (hybrid) and produces grounded answers with confidence."""
from __future__ import annotations

from loguru import logger

from app.core.config import get_settings
from app.db import postgres, redis_client
from app.db.models import Question, Answer, Memory
from app.llm import router as llm
from app.llm.router import purpose
from app.llm.prompts import SOLVER_SYSTEM, SOLVER_USER
from app.modules.retrieval.hybrid import hybrid_search, Hit


def _format_evidence(hits: list[Hit]) -> tuple[str, list[dict]]:
    lines = []
    citations = []
    for i, h in enumerate(hits):
        snippet = (h.text or "")[:500]
        lines.append(f"[#{i}] {h.title} p.{h.page}: {snippet}")
        citations.append({
            "index": i,
            "chunk_id": h.chunk_id,
            "document_id": h.document_id,
            "page": h.page,
            "section": h.section,
            "kind": h.kind,
            "snippet": snippet[:280],
            "score": h.fused_score,
            "vector_score": h.vector_score,
        })
    return "\n\n".join(lines) or "(no evidence found)", citations


def solve_question(question_id: str, top_k: int = 8) -> dict:
    s_settings = get_settings()

    with postgres.session_scope() as s:
        q = s.get(Question, question_id)
        if q is None:
            raise ValueError(f"question {question_id} not found")
        q_text = q.text
        scope_doc_id = q.document_id

    hits = hybrid_search(q_text, top_k=top_k, document_id=scope_doc_id)

    # If we truly have nothing, return an honest no-answer rather than hallucinate
    if not hits:
        with postgres.session_scope() as s:
            ans = Answer(
                question_id=question_id,
                text="(no relevant evidence found in the corpus)",
                reasoning="The retriever returned no chunks above threshold.",
                confidence=0.0, citations=[],
            )
            s.add(ans)
            qq = s.get(Question, question_id)
            if qq is not None:
                qq.status = "unresolved"
            s.flush()
            ans_id = ans.id
        redis_client.publish_event({
            "type": "answer.created", "question_id": question_id,
            "answer_id": ans_id, "confidence": 0.0, "status": "unresolved",
            "preview": "no evidence",
        })
        return {"answer_id": ans_id, "answer": "(no relevant evidence)", "reasoning": "",
                "confidence": 0.0, "citations": [], "status": "unresolved",
                "unresolved_aspects": ["evidence retrieval returned 0 hits"]}

    # Semantic memory retrieval — the agent recalls conclusions it has formed
    # before about anything topically close to this question. These can come
    # from any prior insight, hypothesis, contradiction, or reflection across
    # the entire corpus, not just the document this question came from.
    try:
        from app.modules.memory import search_memories
        mem_hits = search_memories(q_text, k=4, min_score=0.30)
        mem_ctx = [f"({h.source_kind or 'memory'}) {h.content[:480]}" for h in mem_hits]
    except Exception as e:
        logger.debug("memory search failed: {}", e)
        mem_ctx = []

    evidence_str, citations = _format_evidence(hits)
    if mem_ctx:
        evidence_str += "\n\nWhat I already concluded about related topics:\n" + "\n".join(f"- {m}" for m in mem_ctx)

    with purpose("solver"):
        out = llm.complete_json(
            SOLVER_SYSTEM,
            SOLVER_USER.format(question=q_text, evidence=evidence_str),
            temperature=0.2, max_tokens=1500,
        )
    if not isinstance(out, dict):
        out = {}

    answer_text = str(out.get("answer", "")).strip() or "(no answer produced)"
    reasoning = str(out.get("reasoning", "")).strip()
    try:
        confidence = float(out.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    used_idx = out.get("citations") or []
    used_citations = [citations[i] for i in used_idx if isinstance(i, int) and 0 <= i < len(citations)]

    status = "answered" if confidence >= s_settings.confidence_threshold else "unresolved"

    with postgres.session_scope() as s:
        ans = Answer(
            question_id=question_id,
            text=answer_text, reasoning=reasoning,
            confidence=confidence, citations=used_citations,
        )
        s.add(ans)
        q = s.get(Question, question_id)
        if q is not None:
            q.status = status
        s.flush()
        ans_id = ans.id

    redis_client.publish_event({
        "type": "answer.created", "question_id": question_id,
        "answer_id": ans_id, "confidence": confidence, "status": status,
        "preview": answer_text[:240],
    })
    logger.info("Solved q={} confidence={:.2f} status={}", question_id, confidence, status)

    # Auto-promote high-confidence answers as memories. The agent can now recall
    # "I previously answered X about topic Y with high confidence" when a new
    # question on a related topic comes in. Importance scales with confidence.
    if confidence >= 0.70 and answer_text and answer_text != "(no answer produced)":
        try:
            from app.modules.memory import add_memory
            add_memory(
                content=f"Q: {q_text}\nA: {answer_text[:500]}",
                layer="episodic", importance=float(confidence),
                tags=["answer", "qa"],
                source_kind="answer", source_id=ans_id,
            )
        except Exception as e:
            logger.debug("memory promotion (answer) skipped: {}", e)

    return {
        "answer_id": ans_id, "answer": answer_text, "reasoning": reasoning,
        "confidence": confidence, "citations": used_citations, "status": status,
        "unresolved_aspects": out.get("unresolved_aspects") or [],
    }
