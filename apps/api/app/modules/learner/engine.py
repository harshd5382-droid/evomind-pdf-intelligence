"""Self-learning loop — meta-cognition: extract concepts, generate next questions, grow memory."""
from __future__ import annotations

from loguru import logger

from app.core.config import get_settings
from app.db import postgres, redis_client
from app.db.models import Question, Memory
from app.llm import router as llm
from app.llm.router import purpose
from app.llm.prompts import LEARNER_SYSTEM, LEARNER_USER
from app.modules.questioner.engine import VALID_CATEGORIES


def reflect_and_expand(question_id: str, answer_text: str, confidence: float) -> dict:
    s_settings = get_settings()

    with postgres.session_scope() as s:
        q = s.get(Question, question_id)
        if q is None:
            return {}
        parent_text = q.text
        parent_doc = q.document_id
        parent_depth = q.depth

    with purpose("learner"):
        out = llm.complete_json(
            LEARNER_SYSTEM,
            LEARNER_USER.format(question=parent_text, answer=answer_text, confidence=confidence),
            temperature=0.6, max_tokens=1200,
        )
    if not isinstance(out, dict):
        out = {}

    new_qids: list[str] = []

    with postgres.session_scope() as s:
        # Save memory note
        memo = (out.get("memory_note") or "").strip()
        if memo:
            s.add(Memory(layer="long", content=memo, tags=["learner"], importance=max(0.3, min(1.0, confidence))))

        # Save concepts as semantic memories
        for c in (out.get("new_concepts") or [])[:8]:
            if isinstance(c, str) and c.strip():
                s.add(Memory(layer="semantic", content=c.strip(), tags=["concept"], importance=0.5))

        # Spawn child questions if depth allows
        if parent_depth < s_settings.recursion_depth:
            for nq in (out.get("next_questions") or [])[:5]:
                if not isinstance(nq, dict):
                    continue
                cat = str(nq.get("category", "research")).lower().strip()
                if cat not in VALID_CATEGORIES:
                    cat = "research"
                text = str(nq.get("text", "")).strip()
                if not text:
                    continue
                try:
                    pri = float(nq.get("priority", 0.5))
                except Exception:
                    pri = 0.5
                row = Question(
                    text=text, category=cat,
                    document_id=parent_doc, parent_id=question_id,
                    depth=parent_depth + 1, priority=pri,
                )
                s.add(row)
                s.flush()
                new_qids.append(row.id)
                redis_client.publish_event({
                    "type": "question.generated",
                    "question_id": row.id,
                    "parent_id": question_id,
                    "category": cat,
                    "text": text,
                })

    redis_client.publish_event({
        "type": "learner.reflected",
        "question_id": question_id,
        "concepts": (out.get("new_concepts") or [])[:5],
        "new_question_count": len(new_qids),
    })
    logger.info("Reflection on q={} produced {} new questions", question_id, len(new_qids))

    return {
        "new_question_ids": new_qids,
        "concepts": out.get("new_concepts") or [],
        "patterns": out.get("patterns") or [],
        "memory_note": out.get("memory_note") or "",
    }
