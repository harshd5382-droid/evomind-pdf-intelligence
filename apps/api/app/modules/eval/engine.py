"""Answer-quality evaluation.

The intelligence score measures *how much* the agent has produced; this measures
*how good* its answers are. An LLM judge scores each recent grounded answer for
faithfulness to its own cited evidence, and we track:

  - faithfulness: mean judge score over the sample
  - grounded_rate: fraction the judge deemed fully grounded
  - citation_coverage: fraction of answered questions that carry ≥1 citation

Results are persisted as Metric rows (name="eval_faithfulness") so the trend
shows up on /reports alongside the intelligence history.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import func, select

from app.db import postgres
from app.db.models import Answer, Metric, Question
from app.llm import router as llm
from app.llm.prompts import EVAL_JUDGE_SYSTEM, EVAL_JUDGE_USER
from app.llm.router import purpose


def _evidence_from_citations(citations: list) -> str:
    lines = []
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        snippet = str(c.get("snippet") or "").strip()
        title = c.get("title") or c.get("document_id") or "source"
        page = c.get("page")
        lines.append(f"- {title} p.{page}: {snippet}")
    return "\n".join(lines) or "(no evidence attached)"


def _judge(question: str, answer: str, evidence: str) -> dict:
    with purpose("eval"):
        out = llm.complete_json(
            EVAL_JUDGE_SYSTEM,
            EVAL_JUDGE_USER.format(question=question, answer=answer, evidence=evidence),
            temperature=0.0, max_tokens=300,
        )
    if not isinstance(out, dict):
        return {"grounded": False, "score": 0.0, "reason": "judge returned no verdict"}
    try:
        score = float(out.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return {
        "grounded": bool(out.get("grounded")),
        "score": max(0.0, min(1.0, score)),
        "reason": str(out.get("reason", ""))[:300],
    }


def run_eval(sample_size: int = 20) -> dict:
    """Judge a sample of the most recent answers that carry citations."""
    with postgres.session_scope() as s:
        total_answered = s.query(func.count(Question.id)).filter(Question.status == "answered").scalar() or 0
        rows = (
            s.execute(
                select(Answer.id, Answer.text, Answer.citations, Question.text)
                .join(Question, Question.id == Answer.question_id)
                .where(Answer.citations.isnot(None))
                .order_by(Answer.created_at.desc())
                .limit(sample_size * 2)  # over-fetch; some may have empty citations
            ).all()
        )
        # answered questions that have at least one citation on their answer
        with_citations = 0
        for _aid, _atext, cites, _qtext in rows:
            if cites:
                with_citations += 1

    sample = [(aid, atext, cites, qtext) for (aid, atext, cites, qtext) in rows if cites][:sample_size]

    judged = []
    for _aid, atext, cites, qtext in sample:
        verdict = _judge(qtext, atext, _evidence_from_citations(cites))
        judged.append(verdict)

    n = len(judged)
    faithfulness = round(sum(v["score"] for v in judged) / n, 3) if n else 0.0
    grounded_rate = round(sum(1 for v in judged if v["grounded"]) / n, 3) if n else 0.0
    citation_coverage = round(with_citations / total_answered, 3) if total_answered else 0.0

    snapshot = {
        "faithfulness": faithfulness,
        "grounded_rate": grounded_rate,
        "citation_coverage": citation_coverage,
        "sample_size": n,
        "answered_total": int(total_answered),
    }

    with postgres.session_scope() as s:
        s.add(Metric(name="eval_faithfulness", value=faithfulness, extra=snapshot))
    logger.info("Eval: faithfulness={} grounded_rate={} n={}", faithfulness, grounded_rate, n)
    return snapshot


def eval_history(days: int = 30) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(days=days)
    with postgres.session_scope() as s:
        rows = (
            s.query(Metric)
            .filter(Metric.name == "eval_faithfulness", Metric.created_at >= cutoff)
            .order_by(Metric.created_at.asc())
            .all()
        )
    return [{"t": r.created_at.isoformat(), "value": r.value, "extra": r.extra or {}} for r in rows]
