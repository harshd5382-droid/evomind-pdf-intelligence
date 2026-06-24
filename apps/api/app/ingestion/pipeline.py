"""End-to-end ingestion: parse → chunk → embed → persist (Postgres + Qdrant + Neo4j)."""
from __future__ import annotations

import uuid
from pathlib import Path

from loguru import logger

from app.db import postgres, qdrant, neo4j_store, redis_client
from app.db.models import Document, Chunk
from app.ingestion.parser import parse_pdf
from app.ingestion.chunker import chunk_pages
from app.ingestion.extractor import keywords_from_text
from app.llm import router as llm
from app.llm.router import purpose
from app.llm.prompts import CLASSIFY_SUBJECT_SYSTEM, CLASSIFY_SUBJECT_USER


def ingest_pdf(file_path: str | Path, document_id: str | None = None) -> str:
    file_path = Path(file_path)
    parsed = parse_pdf(file_path)

    full_text = "\n".join(p.get("text", "") for p in parsed.pages)
    keywords = keywords_from_text(full_text)

    # Light LLM classification (best-effort; if no key configured, skip gracefully)
    subject = None
    importance = 0.5
    try:
        excerpt = full_text[:4000]
        with purpose("classify"):
            out = llm.complete_json(
                CLASSIFY_SUBJECT_SYSTEM,
                CLASSIFY_SUBJECT_USER.format(title=parsed.title, excerpt=excerpt),
                temperature=0.1, max_tokens=400,
            )
        subject = (out.get("subject") if isinstance(out, dict) else None) or None
        if isinstance(out, dict):
            kws = out.get("keywords") or []
            if isinstance(kws, list) and kws:
                keywords = list(dict.fromkeys([*kws, *keywords]))[:20]
            importance = float(out.get("importance") or 0.5)
    except Exception as e:
        logger.warning("Classification skipped: {}", e)

    chunk_specs = chunk_pages(parsed.pages)
    qdrant.ensure_collection()

    doc_id = document_id or str(uuid.uuid4())
    with postgres.session_scope() as s:
        # If the upload route pre-registered a shell Document (with content_hash
        # set for dedup), update it in place. Otherwise create a fresh row.
        doc = s.get(Document, doc_id)
        if doc is None:
            doc = Document(id=doc_id)
            s.add(doc)
        doc.title = parsed.title or file_path.stem
        doc.author = parsed.author
        doc.filename = file_path.name
        doc.path = str(file_path)
        doc.page_count = parsed.page_count
        doc.subject_area = subject
        doc.importance = importance
        doc.keywords = keywords
        doc.status = "ready"
        for cs in chunk_specs:
            ch = Chunk(
                id=str(uuid.uuid4()),
                document_id=doc.id,
                ord=cs.ord, page=cs.page, text=cs.text,
                section=cs.section, kind=cs.kind, extra={},
            )
            s.add(ch)
        s.flush()
        chunk_records = list(s.query(Chunk).filter(Chunk.document_id == doc.id).order_by(Chunk.ord).all())

    # Embed in batches
    BATCH = 64
    points: list[tuple[str, list[float], dict]] = []
    for i in range(0, len(chunk_records), BATCH):
        batch = chunk_records[i:i + BATCH]
        vecs = llm.embed([c.text for c in batch])
        for c, v in zip(batch, vecs):
            points.append((c.id, v, {
                "document_id": c.document_id,
                "chunk_id": c.id,
                "page": c.page,
                "kind": c.kind,
                "section": c.section,
                "title": parsed.title,
                "text": c.text[:600],
            }))
    qdrant.upsert_chunks(points)

    # Graph: paper node + section + topic nodes
    try:
        neo4j_store.upsert_node("Paper", doc_id, {
            "id": doc_id, "title": parsed.title or file_path.stem,
            "subject": subject or "", "importance": importance,
        })
        for kw in keywords[:10]:
            neo4j_store.upsert_node("Concept", f"concept:{kw}", {"id": f"concept:{kw}", "name": kw})
            neo4j_store.upsert_edge("Paper", doc_id, "Concept", f"concept:{kw}", "MENTIONS")
    except Exception as e:
        logger.warning("Neo4j skipped: {}", e)

    redis_client.publish_event({
        "type": "document.ingested",
        "document_id": doc_id,
        "title": parsed.title or file_path.stem,
        "pages": parsed.page_count,
        "chunks": len(chunk_specs),
        "parser": parsed.used_parser,
    })

    logger.info("Ingested {} (chunks={}, parser={})", parsed.title, len(chunk_specs), parsed.used_parser)

    # ── Autopilot hand-off: seed root questions immediately so the autopilot
    # loop can start solving without waiting for the next seed-cycle tick.
    # Best-effort: failures here must not break ingest.
    try:
        from app.modules.questioner.engine import generate_for_document
        qids = generate_for_document(doc_id)
        logger.info("post-ingest: seeded {} questions for doc {}", len(qids), doc_id)
    except Exception as e:
        logger.warning("post-ingest question seeding skipped: {}", e)

    return doc_id
