"""Self-question engine — generates intelligence-increasing questions from documents.

Includes embedding-based dedupe so repeat ingests of similar content don't
re-spawn near-identical root questions.
"""
from __future__ import annotations

import math

from loguru import logger
from sqlalchemy import select

from app.core.config import get_settings
from app.db import postgres, redis_client
from app.db.models import Chunk, Document, Question
from app.llm import router as llm
from app.llm.prompts import QUESTION_GENERATOR_SYSTEM, QUESTION_GENERATOR_USER
from app.llm.router import purpose

VALID_CATEGORIES = {
    "understanding", "deep_logic", "missing_data", "contradiction",
    "math", "application", "research", "meta", "improvement",
    "ethics", "cost", "reproducibility",
}

DEDUPE_SIM_THRESHOLD = 0.92  # cosine sim above which a candidate is considered a near-duplicate


def _doc_context(doc: Document, chunks: list[Chunk], char_budget: int = 6000) -> str:
    if not chunks:
        return ""
    n = len(chunks)
    picks = []
    for idx in {0, n // 4, n // 2, (3 * n) // 4, n - 1}:
        if 0 <= idx < n:
            picks.append(chunks[idx])
    picks = sorted(picks, key=lambda c: c.ord)
    out, used = [], 0
    for c in picks:
        snippet = c.text[:1200]
        block = f"[p.{c.page} {c.section or ''}] {snippet}"
        if used + len(block) > char_budget:
            break
        out.append(block); used += len(block)
    return "\n\n".join(out)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def _existing_question_embeddings(document_id: str) -> list[tuple[str, list[float]]]:
    """Return [(text, embedding)] for existing questions on this doc, computed on demand."""
    with postgres.session_scope() as s:
        rows = list(s.scalars(select(Question).where(Question.document_id == document_id)))
        texts = [r.text for r in rows]
    if not texts:
        return []
    vecs = llm.embed(texts)
    return list(zip(texts, vecs))


def generate_for_document(document_id: str, n: int | None = None) -> list[str]:
    s_settings = get_settings()
    n = n or s_settings.questions_per_doc

    with postgres.session_scope() as s:
        doc = s.get(Document, document_id)
        if doc is None:
            raise ValueError(f"document {document_id} not found")
        chunks = list(s.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ord)))
        ctx = _doc_context(doc, chunks)
        title = doc.title

    with purpose("questioner"):
        out = llm.complete_json(
            QUESTION_GENERATOR_SYSTEM,
            QUESTION_GENERATOR_USER.format(title=title, context=ctx, n=n),
            temperature=0.7, max_tokens=1800,
        )
    raw = (out or {}).get("questions") if isinstance(out, dict) else None
    if not isinstance(raw, list):
        logger.warning("Questioner returned no list. Output: {}", out)
        return []

    # Build a snapshot of existing question embeddings to compare against.
    existing = _existing_question_embeddings(document_id)
    existing_vecs = [v for _, v in existing]

    # Embed candidate texts in one batch
    candidates: list[dict] = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        text = str(q.get("text", "")).strip()
        if not text:
            continue
        cat = str(q.get("category", "understanding")).lower().strip()
        if cat not in VALID_CATEGORIES:
            cat = "understanding"
        try:
            priority = float(q.get("priority", 0.5))
        except Exception:
            priority = 0.5
        candidates.append({"text": text, "category": cat, "priority": priority})
    if not candidates:
        return []

    cand_vecs = llm.embed([c["text"] for c in candidates])

    inserted: list[str] = []
    skipped_dupes = 0
    accepted_vecs: list[list[float]] = list(existing_vecs)

    with postgres.session_scope() as s:
        for c, cv in zip(candidates, cand_vecs):
            # Skip if too similar to anything already in the corpus or accepted this batch
            sim = max((_cosine(cv, ev) for ev in accepted_vecs), default=0.0)
            if sim >= DEDUPE_SIM_THRESHOLD:
                skipped_dupes += 1
                continue
            row = Question(
                text=c["text"], category=c["category"], document_id=document_id,
                depth=0, priority=c["priority"],
            )
            s.add(row); s.flush()
            inserted.append(row.id)
            accepted_vecs.append(cv)
            redis_client.publish_event({
                "type": "question.generated",
                "question_id": row.id, "document_id": document_id,
                "category": c["category"], "text": c["text"],
            })

    logger.info("Generated {} questions for doc {} (deduped {})", len(inserted), document_id, skipped_dupes)
    return inserted
