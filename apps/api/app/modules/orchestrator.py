"""Autonomous research cycle.

A single cycle: pick high-priority open questions → solve → reflect → spawn next-gen
questions → synthesize topics → propose hypotheses → detect contradictions → score.
"""
from __future__ import annotations

import math
from itertools import combinations

from loguru import logger
from sqlalchemy import select, func, asc, desc

from app.core.config import get_settings
from app.db import postgres, redis_client
from app.db.models import Document, Question, Answer, Memory
from app.llm import router as llm
from app.modules.questioner.engine import generate_for_document
from app.modules.solver.engine import solve_question
from app.modules.learner.engine import reflect_and_expand
from app.modules.knowledge.synthesis import (
    synthesize_topic, generate_hypotheses_from_top_insights, detect_pairwise_contradiction,
)
from app.modules.intelligence.scorer import compute_score


def _seed_questions_for_unseeded_docs() -> int:
    seeded = 0
    with postgres.session_scope() as s:
        rows = s.execute(select(Document.id).where(Document.status == "ready")).scalars().all()
    for doc_id in rows:
        with postgres.session_scope() as s:
            existing = s.query(func.count(Question.id)).filter(Question.document_id == doc_id).scalar() or 0
        if existing == 0:
            try:
                ids = generate_for_document(doc_id)
                seeded += len(ids)
            except Exception as e:
                logger.warning("Seeding questions failed for doc {}: {}", doc_id, e)
    return seeded


def _pick_open_questions(limit: int) -> list[str]:
    with postgres.session_scope() as s:
        rows = (
            s.query(Question.id)
            .filter(Question.status == "open")
            .order_by(Question.priority.desc(), asc(Question.created_at))
            .limit(limit)
            .all()
        )
    return [r[0] for r in rows]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def _scan_for_contradictions(answer_ids: list[str], max_pairs: int = 6) -> int:
    """Pick the highest-confidence recent answers, find topically similar pairs from
    DIFFERENT documents, and run the contradiction LLM. Returns number of contradictions saved.
    """
    if not answer_ids:
        return 0
    with postgres.session_scope() as s:
        ans = s.query(Answer).filter(Answer.id.in_(answer_ids), Answer.confidence >= 0.5).all()
    # Pull the first citation snippet per answer
    items: list[dict] = []
    for a in ans:
        cites = a.citations or []
        if not cites:
            continue
        top = cites[0]
        snippet = top.get("snippet") or ""
        if not snippet:
            continue
        items.append({
            "answer_id": a.id,
            "snippet": snippet,
            "doc": top.get("document_id") or "",
            "chunk": top.get("chunk_id") or "",
        })
    if len(items) < 2:
        return 0

    vecs = llm.embed([it["snippet"] for it in items])
    # Find cross-document pairs that are topically close
    candidates: list[tuple[float, int, int]] = []
    for i, j in combinations(range(len(items)), 2):
        if items[i]["doc"] == items[j]["doc"]:
            continue
        sim = _cosine(vecs[i], vecs[j])
        if sim >= 0.55:
            candidates.append((sim, i, j))
    candidates.sort(reverse=True)

    saved = 0
    for _, i, j in candidates[:max_pairs]:
        try:
            cid = detect_pairwise_contradiction(
                items[i]["snippet"], items[j]["snippet"],
                a_chunk_id=items[i]["chunk"], b_chunk_id=items[j]["chunk"],
            )
            if cid:
                saved += 1
        except Exception as e:
            logger.debug("contradiction check failed: {}", e)
    return saved


def run_cycle(question_budget: int = 8, synthesize_top_keywords: bool = True) -> dict:
    settings = get_settings()
    redis_client.publish_event({"type": "cycle.started", "budget": question_budget})

    seeded = _seed_questions_for_unseeded_docs()
    qids = _pick_open_questions(question_budget)
    solved_answer_ids: list[str] = []
    expanded = 0

    for qid in qids:
        try:
            res = solve_question(qid)
            if res.get("answer_id"):
                solved_answer_ids.append(res["answer_id"])
            try:
                exp = reflect_and_expand(qid, res["answer"], res["confidence"])
                expanded += len(exp.get("new_question_ids", []))
            except Exception as e:
                logger.warning("Reflection failed for q={}: {}", qid, e)
        except Exception as e:
            logger.exception("Solver failed for q={}: {}", qid, e)

    insights = 0
    if synthesize_top_keywords:
        topics = _topics_for_synthesis()
        for t in topics[:3]:
            try:
                if synthesize_topic(t):
                    insights += 1
            except Exception as e:
                logger.warning("Synthesis on '{}' failed: {}", t, e)

    hyps = 0
    try:
        hyps = len(generate_hypotheses_from_top_insights())
    except Exception as e:
        logger.warning("Hypothesis stage failed: {}", e)

    contradictions = 0
    try:
        contradictions = _scan_for_contradictions(solved_answer_ids)
    except Exception as e:
        logger.warning("Contradiction scan failed: {}", e)

    snapshot = compute_score()
    summary = {
        "seeded_questions": seeded,
        "solved": len(solved_answer_ids),
        "spawned_questions": expanded,
        "insights": insights,
        "hypotheses": hyps,
        "contradictions": contradictions,
        "intelligence": snapshot,
    }
    redis_client.publish_event({"type": "cycle.completed", **summary})
    logger.info("Cycle complete: {}", summary)
    return summary


def _topics_for_synthesis() -> list[str]:
    with postgres.session_scope() as s:
        docs = s.query(Document).all()
        bag: dict[str, int] = {}
        for d in docs:
            for k in (d.keywords or []):
                bag[k] = bag.get(k, 0) + 1
        subjects = [d.subject_area for d in docs if d.subject_area]
    topics = sorted(bag.items(), key=lambda kv: kv[1], reverse=True)
    out, seen = [], set()
    for sub in subjects:
        if sub and sub.lower() not in seen:
            out.append(sub); seen.add(sub.lower())
    for k, _ in topics:
        if k.lower() not in seen and len(out) < 8:
            out.append(k); seen.add(k.lower())
    return out


def run_daily_research() -> dict:
    redis_client.publish_event({"type": "daily.started"})
    summary = run_cycle(question_budget=20, synthesize_top_keywords=True)

    with postgres.session_scope() as s:
        latest = s.query(Memory).order_by(Memory.created_at.desc()).limit(20).all()
        if latest:
            digest = " | ".join(m.content[:140] for m in latest if m.content)
            s.add(Memory(layer="long", content=f"Daily digest: {digest[:1500]}", tags=["daily", "digest"], importance=0.7))

    redis_client.publish_event({"type": "daily.completed", **summary})
    return summary
