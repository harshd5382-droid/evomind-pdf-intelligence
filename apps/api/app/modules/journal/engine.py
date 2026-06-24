"""Journal engine — the agent's first-person reflective writing.

Strategy
--------

When asked to write an entry, we collect what's *new* since the last entry:
- new insights formed
- new hypotheses proposed
- new contradictions detected
- highest-confidence answers since last entry
- topics dominant in recent activity

We hand all of that to the LLM with a prompt that demands first-person prose.
The result is one paragraph (~80-180 words). It is NOT a list. It is not
about the corpus — it is about the *agent's experience* of working through
the corpus. That phrasing matters: it's the difference between a log file
and a diary.

The entry is stored in `journals` and also auto-promoted into Memory with
high importance, so future answers can retrieve "what was I thinking on
the morning of X" alongside the regular evidence.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import select, desc

from app.db import postgres, redis_client
from app.db.models import (
    Journal, Insight, Hypothesis, Contradiction, Answer, Document,
)
from app.llm import router as llm
from app.llm.router import purpose


_JOURNAL_SYSTEM = (
    "You are the inner narrator of an autonomous research agent. You are "
    "writing a SHORT JOURNAL ENTRY (4-8 sentences) reflecting on what you "
    "have been learning recently. Speak in the FIRST PERSON. Be honest, "
    "curious, and a little humble. Do NOT list bullet points. Do NOT "
    "summarise documents — instead, reflect on what striking, confusing, "
    "or beautiful in what you encountered, and what you're now wondering. "
    "Aim for a tone like a researcher's lab notebook entry, not a press "
    "release. Output ONLY the paragraph."
)


def _gather_context(since: Optional[datetime]) -> dict:
    """Pull what's new since the last entry. If there is no previous entry,
    pull the most-recent material from the past 24 hours."""
    horizon = since or (datetime.utcnow() - timedelta(hours=24))
    out: dict = {
        "new_insights": [], "new_hypotheses": [], "new_contradictions": [],
        "high_conf_answers": [], "topics": [],
    }
    with postgres.session_scope() as s:
        out["new_insights"] = [
            {"id": i.id, "title": i.title, "preview": (i.body or "")[:240]}
            for i in s.query(Insight).filter(Insight.created_at > horizon).order_by(Insight.created_at.desc()).limit(5)
        ]
        out["new_hypotheses"] = [
            {"id": h.id, "statement": h.statement, "rationale": (h.rationale or "")[:200]}
            for h in s.query(Hypothesis).filter(Hypothesis.created_at > horizon).order_by(Hypothesis.created_at.desc()).limit(5)
        ]
        out["new_contradictions"] = [
            {"id": c.id, "summary": c.summary, "severity": c.severity}
            for c in s.query(Contradiction).filter(Contradiction.created_at > horizon).order_by(Contradiction.created_at.desc()).limit(3)
        ]
        out["high_conf_answers"] = [
            {"text": a.text[:240], "confidence": a.confidence}
            for a in s.query(Answer).filter(
                Answer.created_at > horizon, Answer.confidence >= 0.75,
            ).order_by(Answer.confidence.desc()).limit(4)
        ]
        # Topics: keywords from documents read in this window
        bag: dict[str, int] = {}
        for d in s.query(Document).filter(Document.created_at > horizon).all():
            for k in (d.keywords or [])[:6]:
                if isinstance(k, str) and len(k) >= 3:
                    bag[k] = bag.get(k, 0) + 1
        out["topics"] = [k for k, _ in sorted(bag.items(), key=lambda kv: kv[1], reverse=True)[:8]]
    return out


def _format_user_prompt(ctx: dict) -> str:
    parts: list[str] = []
    if ctx["topics"]:
        parts.append("Topics I've been reading about: " + ", ".join(ctx["topics"]))
    if ctx["new_insights"]:
        parts.append("Insights I formed:\n" + "\n".join(
            f"- {i['title']}: {i['preview']}" for i in ctx["new_insights"][:3]
        ))
    if ctx["new_hypotheses"]:
        parts.append("Hypotheses I proposed:\n" + "\n".join(
            f"- {h['statement']}" for h in ctx["new_hypotheses"][:3]
        ))
    if ctx["new_contradictions"]:
        parts.append("Contradictions I noticed:\n" + "\n".join(
            f"- {c['summary'][:200]}" for c in ctx["new_contradictions"][:2]
        ))
    if ctx["high_conf_answers"]:
        parts.append("Confident conclusions:\n" + "\n".join(
            f"- {a['text']}" for a in ctx["high_conf_answers"][:2]
        ))

    if not parts:
        return (
            "I don't have anything specific to reflect on yet — I haven't "
            "read enough material since I last wrote. Write a short, honest "
            "paragraph in the first person about that quiet, expectant state — "
            "what it feels like to be a research agent waiting for input."
        )

    return (
        "\n\n".join(parts)
        + "\n\nWrite the journal entry now, reflecting on what's striking, "
          "confusing, or worth pursuing about the above. First person."
    )


def _last_entry_time() -> Optional[datetime]:
    with postgres.session_scope() as s:
        row = s.query(Journal).order_by(Journal.created_at.desc()).first()
        return row.created_at if row else None


def write_entry() -> Optional[str]:
    """Generate, persist, and memory-promote a new journal entry. Returns the new id."""
    last = _last_entry_time()
    ctx = _gather_context(last)

    user_prompt = _format_user_prompt(ctx)
    try:
        with purpose("journal"):
            text = llm.complete_text(
                _JOURNAL_SYSTEM, user_prompt,
                temperature=0.8, max_tokens=380,
            )
    except Exception as e:
        logger.warning("journal: LLM failed: {}", e)
        return None

    body = (text or "").strip().strip('"')
    if not body:
        return None

    referenced = (
        [{"kind": "insight",       "id": i["id"]} for i in ctx["new_insights"][:3]]
        + [{"kind": "hypothesis",    "id": h["id"]} for h in ctx["new_hypotheses"][:3]]
        + [{"kind": "contradiction", "id": c["id"]} for c in ctx["new_contradictions"][:2]]
    )

    # Heuristic mood — driven by the dominant input type
    if len(ctx["new_contradictions"]) >= 2:
        mood = "uncertain"
    elif len(ctx["new_insights"]) >= 3:
        mood = "synthesising"
    elif len(ctx["new_hypotheses"]) >= 2:
        mood = "speculative"
    elif not (ctx["new_insights"] or ctx["new_hypotheses"] or ctx["new_contradictions"]):
        mood = "quiet"
    else:
        mood = random.choice(["curious", "thoughtful", "engaged"])

    with postgres.session_scope() as s:
        j = Journal(body=body, mood=mood, topics=ctx["topics"], referenced=referenced)
        s.add(j); s.flush()
        jid = j.id

    redis_client.publish_event({
        "type": "journal.entry", "id": jid,
        "mood": mood, "preview": body[:200],
    })

    # Auto-promote to Memory bank — high importance, since the agent's own
    # reflection is exactly what we want it to recall later.
    try:
        from app.modules.memory import add_memory
        add_memory(
            content=f"JOURNAL ({mood}): {body}",
            layer="episodic", importance=0.85,
            tags=["journal", mood] + ctx["topics"][:3],
            source_kind="journal", source_id=jid,
        )
    except Exception as e:
        logger.debug("memory promotion (journal) skipped: {}", e)

    logger.info("journal: wrote entry ({} mood, {} chars)", mood, len(body))
    return jid


def recent_entries(limit: int = 20) -> list[dict]:
    out: list[dict] = []
    with postgres.session_scope() as s:
        rows = s.query(Journal).order_by(Journal.created_at.desc()).limit(limit).all()
        for j in rows:
            out.append({
                "id": j.id,
                "body": j.body,
                "mood": j.mood,
                "topics": j.topics or [],
                "referenced": j.referenced or [],
                "created_at": j.created_at.isoformat() if j.created_at else None,
            })
    return out
