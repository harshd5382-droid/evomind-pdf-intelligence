"""Knowledge creation: cross-document synthesis, contradiction detection, hypothesis generation."""
from __future__ import annotations

from loguru import logger

from app.db import neo4j_store, postgres, qdrant, redis_client
from app.db.models import Contradiction, Hypothesis, Insight
from app.llm import router as llm
from app.llm.prompts import (
    CONTRADICTION_SYSTEM,
    CONTRADICTION_USER,
    HYPOTHESIS_SYSTEM,
    HYPOTHESIS_USER,
    SYNTHESIS_SYSTEM,
    SYNTHESIS_USER,
)
from app.llm.router import purpose


def synthesize_topic(topic: str, top_k: int = 12) -> str | None:
    """Pull cross-document evidence for a topic and produce a unified Insight."""
    qdrant.ensure_collection()
    vec = llm.embed([topic], kind="query")[0]
    hits = qdrant.search(vec, top_k=top_k)
    if not hits:
        return None

    evidence_lines = []
    sources = []
    for i, h in enumerate(hits):
        p = h.get("payload", {}) or {}
        evidence_lines.append(f"[{i}] {p.get('title','?')} p.{p.get('page','?')}: {(p.get('text') or '')[:400]}")
        sources.append({
            "chunk_id": p.get("chunk_id"),
            "document_id": p.get("document_id"),
            "page": p.get("page"),
        })

    with purpose("synthesis"):
        out = llm.complete_json(
            SYNTHESIS_SYSTEM,
            SYNTHESIS_USER.format(topic=topic, evidence="\n".join(evidence_lines)),
            temperature=0.4, max_tokens=1800,
        )
    if not isinstance(out, dict):
        return None

    title = out.get("title") or f"Synthesis: {topic}"
    summary = out.get("summary") or ""
    body_parts = [summary]
    if out.get("agreements"):
        body_parts.append("\n\nAgreements:\n- " + "\n- ".join(out["agreements"]))
    if out.get("disagreements"):
        body_parts.append("\n\nDisagreements:\n- " + "\n- ".join(out["disagreements"]))
    if out.get("open_questions"):
        body_parts.append("\n\nOpen questions:\n- " + "\n- ".join(out["open_questions"]))

    with postgres.session_scope() as s:
        ins = Insight(title=title, body="".join(body_parts), kind="synthesis", sources=sources)
        s.add(ins)
        s.flush()
        ins_id = ins.id

    # Auto-promote to memory: this insight is now part of the agent's
    # retrievable cognitive history, not just a row to display in /reports.
    try:
        from app.modules.memory import add_memory
        add_memory(
            content=f"INSIGHT: {title}\n{summary}",
            layer="long", importance=0.7,
            tags=["insight", "synthesis", topic],
            source_kind="insight", source_id=ins_id,
        )
    except Exception as e:
        logger.debug("memory promotion (insight) skipped: {}", e)

    redis_client.publish_event({"type": "insight.created", "id": ins_id, "title": title, "kind": "synthesis"})
    return ins_id


def generate_hypotheses_from_top_insights(limit: int = 6) -> list[str]:
    """Take recent insights and propose testable hypotheses grounded in them."""
    with postgres.session_scope() as s:
        recent = s.query(Insight).order_by(Insight.created_at.desc()).limit(limit).all()
        observations = [f"[{i}] {ins.title}: {ins.body[:600]}" for i, ins in enumerate(recent)]
    if not observations:
        return []

    with purpose("hypothesis"):
        out = llm.complete_json(
            HYPOTHESIS_SYSTEM,
            HYPOTHESIS_USER.format(observations="\n".join(observations)),
            temperature=0.7, max_tokens=1400,
        )
    if not isinstance(out, dict):
        return []

    ids: list[str] = []
    with postgres.session_scope() as s:
        for h in (out.get("hypotheses") or [])[:8]:
            if not isinstance(h, dict):
                continue
            stmt = (h.get("statement") or "").strip()
            if not stmt:
                continue
            row = Hypothesis(
                statement=stmt,
                rationale=h.get("rationale", "") or "",
                testable=bool(h.get("testable", True)),
                supporting=h.get("supporting") or [],
                opposing=h.get("opposing") or [],
            )
            s.add(row)
            s.flush()
            ids.append(row.id)
            hyp_id = row.id
            redis_client.publish_event({"type": "hypothesis.created", "id": hyp_id, "statement": stmt[:200]})
            try:
                neo4j_store.upsert_node("Hypothesis", hyp_id, {"id": hyp_id, "statement": stmt[:240]})
            except Exception as e:
                logger.warning("Neo4j hypothesis upsert skipped: {}", e)
            # Auto-promote: this hypothesis is now retrievable in the agent's memory.
            try:
                from app.modules.memory import add_memory
                add_memory(
                    content=f"HYPOTHESIS: {stmt}\nRationale: {h.get('rationale', '')}",
                    layer="long", importance=0.65,
                    tags=["hypothesis"],
                    source_kind="hypothesis", source_id=hyp_id,
                )
            except Exception as e:
                logger.debug("memory promotion (hypothesis) skipped: {}", e)
    return ids


def detect_pairwise_contradiction(passage_a: str, passage_b: str, a_chunk_id: str | None = None, b_chunk_id: str | None = None) -> str | None:
    with purpose("contradiction"):
        out = llm.complete_json(
            CONTRADICTION_SYSTEM,
            CONTRADICTION_USER.format(a=passage_a[:1200], b=passage_b[:1200]),
            temperature=0.1, max_tokens=400,
        )
    if not isinstance(out, dict):
        return None
    if not out.get("is_contradiction"):
        return None
    with postgres.session_scope() as s:
        row = Contradiction(
            summary=out.get("summary", "") or "",
            a_chunk_id=a_chunk_id,
            b_chunk_id=b_chunk_id,
            severity=float(out.get("severity") or 0.5),
        )
        s.add(row)
        s.flush()
        rid = row.id
    redis_client.publish_event({"type": "contradiction.detected", "id": rid, "summary": out.get("summary", "")[:200]})
    # Auto-promote: contradictions become "current confusion" the agent can recall.
    try:
        from app.modules.memory import add_memory
        add_memory(
            content=f"CONTRADICTION: {out.get('summary', '')}\nA: {passage_a[:300]}\nB: {passage_b[:300]}",
            layer="long",
            importance=min(1.0, 0.5 + 0.5 * float(out.get("severity") or 0.5)),
            tags=["contradiction"],
            source_kind="contradiction", source_id=rid,
        )
    except Exception as e:
        logger.debug("memory promotion (contradiction) skipped: {}", e)
    return rid
