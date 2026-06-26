"""Curiosity engine — find what the agent doesn't yet understand and ask about it.

Implementation
--------------

`compute_gaps()` runs four cheap SQL passes (no LLM calls) to score four
kinds of gaps:

1. **Uncovered concepts** — keywords across the corpus with very few
   questions touching them.
2. **Weak hypotheses** — hypotheses with thin supporting evidence and
   non-trivial age.
3. **Low-confidence answers** — questions resolved at confidence < 0.6.
4. **Open contradictions** — recent contradictions the agent never
   followed up on.

Scoring is intentionally simple so we can reason about it. We rebuild
every ~10 min (configurable) — that's cheap enough we don't need cleverer
incremental update logic.

`seed_gap_questions()` consumes the top gaps, generates targeted questions
via the LLM, and inserts them with a higher base priority than the regular
questioner. The autopilot calls this on its solve cadence: a fraction
(default 40%) of new question slots go to curiosity-driven questions.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import func

from app.db import postgres, redis_client
from app.db.models import (
    Answer,
    Contradiction,
    CuriosityGap,
    Document,
    Hypothesis,
    Question,
)
from app.llm import router as llm
from app.llm.router import purpose

# ---------------------------------------------------------------------------
# Gap scoring (no LLM calls)
# ---------------------------------------------------------------------------

def _score_uncovered_concepts(top_n: int = 8) -> list[dict]:
    """Concepts (keywords) that appear in many docs but have few questions about them."""
    counts: Counter[str] = Counter()
    with postgres.session_scope() as s:
        for d in s.query(Document).all():
            for k in (d.keywords or []):
                if isinstance(k, str) and len(k) >= 4:
                    counts[k.lower()] += 1
        # crude: count questions whose text contains the keyword (case-insensitive)
        gaps = []
        for kw, n_docs in counts.most_common(40):
            if n_docs < 2:  # only consider concepts that appeared in multiple docs
                continue
            # how many questions mention this concept
            try:
                like = f"%{kw}%"
                q_count = s.query(func.count(Question.id)).filter(
                    Question.text.ilike(like)
                ).scalar() or 0
            except Exception:
                q_count = 0
            # density = questions per doc-mention. Low density = under-explored.
            density = q_count / max(1, n_docs)
            if density >= 1.5:
                continue
            score = (n_docs ** 0.5) * (1.0 / (1.0 + density))
            gaps.append({
                "topic": kw,
                "kind": "uncovered_concept",
                "score": round(float(score), 4),
                "rationale": f"appears in {n_docs} documents but has only {q_count} questions",
            })
    gaps.sort(key=lambda g: g["score"], reverse=True)
    return gaps[:top_n]


def _score_weak_hypotheses(top_n: int = 4) -> list[dict]:
    """Hypotheses with thin support relative to their age."""
    out: list[dict] = []
    now = datetime.utcnow()
    with postgres.session_scope() as s:
        for h in s.query(Hypothesis).order_by(Hypothesis.created_at.desc()).limit(40).all():
            supporting = len(h.supporting or [])
            opposing = len(h.opposing or [])
            age_h = max(0.0, (now - h.created_at).total_seconds() / 3600.0)
            # A hypothesis older than 30 minutes with <2 pieces of support is "weak".
            if age_h > 0.5 and supporting < 2:
                score = 1.0 + 0.1 * age_h - 0.5 * supporting + 0.2 * opposing
                out.append({
                    "topic": h.statement[:120],
                    "kind": "weak_hypothesis",
                    "score": round(float(score), 4),
                    "rationale": f"{supporting} supports, {opposing} opposes, {age_h:.1f}h old",
                })
    out.sort(key=lambda g: g["score"], reverse=True)
    return out[:top_n]


def _score_low_confidence_answers(top_n: int = 4) -> list[dict]:
    """Questions answered at confidence < 0.6 — the agent's own admission of uncertainty."""
    out: list[dict] = []
    with postgres.session_scope() as s:
        rows = (
            s.query(Question, Answer)
            .join(Answer, Answer.question_id == Question.id)
            .filter(Answer.confidence < 0.6, Answer.confidence > 0.0)
            .order_by(Answer.confidence.asc(), Answer.created_at.desc())
            .limit(top_n)
            .all()
        )
        for q, a in rows:
            out.append({
                "topic": q.text[:160],
                "kind": "low_confidence",
                "score": round(1.0 - float(a.confidence), 4),
                "rationale": f"answered at {a.confidence:.0%} confidence",
            })
    return out


def _score_open_contradictions(top_n: int = 3) -> list[dict]:
    """Recent contradictions with high severity that haven't been addressed."""
    out: list[dict] = []
    with postgres.session_scope() as s:
        rows = (
            s.query(Contradiction)
            .order_by(Contradiction.created_at.desc())
            .limit(10).all()
        )
        for c in rows:
            score = 0.5 + 0.5 * float(c.severity or 0.5)
            out.append({
                "topic": (c.summary or "")[:200],
                "kind": "open_contradiction",
                "score": round(score, 4),
                "rationale": f"severity {(c.severity or 0):.0%}",
            })
    out.sort(key=lambda g: g["score"], reverse=True)
    return out[:top_n]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_gaps() -> list[dict]:
    """Recompute all four kinds of gaps and persist a fresh snapshot.

    Old `addressed=False` rows are wiped each pass so we don't accumulate
    stale gap descriptions. Addressed gaps (those that produced questions)
    are kept for ~24h as a record of what curiosity acted on.
    """
    found = (
        _score_uncovered_concepts()
        + _score_weak_hypotheses()
        + _score_low_confidence_answers()
        + _score_open_contradictions()
    )
    found.sort(key=lambda g: g["score"], reverse=True)

    horizon = datetime.utcnow() - timedelta(hours=24)
    with postgres.session_scope() as s:
        # Drop unaddressed rows — we replace them wholesale.
        s.query(CuriosityGap).filter(CuriosityGap.addressed.is_(False)).delete()
        # Drop addressed rows older than 24h.
        s.query(CuriosityGap).filter(
            CuriosityGap.addressed.is_(True),
            CuriosityGap.created_at < horizon,
        ).delete()

        for g in found[:20]:
            s.add(CuriosityGap(
                topic=g["topic"], kind=g["kind"],
                score=float(g["score"]), rationale=g["rationale"],
                addressed=False,
            ))

    logger.info("curiosity: computed {} gaps (top: {})", len(found), found[:3])
    redis_client.publish_event({"type": "curiosity.computed", "count": len(found)})
    return found


def current_gaps(limit: int = 12, kind: str | None = None) -> list[dict]:
    out: list[dict] = []
    with postgres.session_scope() as s:
        q = s.query(CuriosityGap).filter(CuriosityGap.addressed.is_(False))
        if kind:
            q = q.filter(CuriosityGap.kind == kind)
        for g in q.order_by(CuriosityGap.score.desc()).limit(limit).all():
            out.append({
                "id": g.id, "topic": g.topic, "kind": g.kind,
                "score": float(g.score), "rationale": g.rationale,
                "addressed": g.addressed,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            })
    return out


# ---------------------------------------------------------------------------
# Question seeding from gaps
# ---------------------------------------------------------------------------

_GAP_QUESTION_SYSTEM = (
    "You are an autonomous research agent. Given ONE area where your "
    "knowledge is weak or uncertain, propose 1-2 specific, answerable "
    "research questions you should ask yourself to close that gap. The "
    "questions must be concrete (not 'tell me about X') and groundable "
    "in scientific literature. Return STRICT JSON: "
    '{"questions": [{"text": "...", "category": "missing_data|deep_logic|contradiction|research|application", "priority": 0.0-1.0}]}'
)


def _gap_to_prompt(gap: dict) -> str:
    return (
        f"Gap kind: {gap['kind']}\n"
        f"Topic: {gap['topic']}\n"
        f"Why this is a gap: {gap['rationale']}\n\n"
        "Propose 1-2 concrete questions to close this gap."
    )


def seed_gap_questions(max_gaps: int = 3) -> list[str]:
    """Take the top unaddressed gaps and turn them into Question rows.

    Returns the list of new question ids. Marks the gaps as `addressed=True`
    once a question is created from them, so we don't re-ask the same
    question every cycle.
    """
    gaps = current_gaps(limit=max_gaps * 2)
    if not gaps:
        return []

    new_qids: list[str] = []
    used_gap_ids: list[str] = []

    for gap in gaps[:max_gaps]:
        try:
            with purpose("curiosity"):
                out = llm.complete_json(
                    _GAP_QUESTION_SYSTEM, _gap_to_prompt(gap),
                    temperature=0.65, max_tokens=420,
                )
        except Exception as e:
            logger.warning("curiosity: LLM failed for gap {}: {}", gap["id"], e)
            continue

        if not isinstance(out, dict):
            continue
        proposals = out.get("questions") or []
        if not isinstance(proposals, list):
            continue

        with postgres.session_scope() as s:
            for p in proposals[:2]:
                if not isinstance(p, dict):
                    continue
                text = (p.get("text") or "").strip()
                if not text or len(text) < 10:
                    continue
                cat = p.get("category", "research")
                if cat not in {"understanding","deep_logic","missing_data","contradiction","math","application","research","meta","improvement"}:
                    cat = "research"
                # Curiosity-driven questions get a small priority boost over
                # the regular per-document questioner so they get solved first.
                pri = max(0.0, min(1.0, float(p.get("priority", 0.7))))
                pri = max(pri, 0.65)
                row = Question(
                    text=text, category=cat, document_id=None,
                    parent_id=None, depth=0, status="open",
                    priority=pri,
                )
                s.add(row); s.flush()
                new_qids.append(row.id)
                redis_client.publish_event({
                    "type": "question.generated",
                    "id": row.id, "text": text[:200],
                    "source": "curiosity", "gap_kind": gap["kind"],
                })
        used_gap_ids.append(gap["id"])

    # Mark used gaps as addressed
    if used_gap_ids:
        with postgres.session_scope() as s:
            s.query(CuriosityGap).filter(
                CuriosityGap.id.in_(used_gap_ids)
            ).update({CuriosityGap.addressed: True}, synchronize_session=False)

    if new_qids:
        logger.info("curiosity: seeded {} gap-driven questions", len(new_qids))
    return new_qids
