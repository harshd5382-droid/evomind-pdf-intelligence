"""Hybrid retrieval: dense vectors (Qdrant) + sparse keywords (BM25), fused with RRF.

Why hybrid: pure vector retrieval misses literal terms (formulas, named entities, IDs,
acronyms). Pure BM25 misses paraphrases. Reciprocal Rank Fusion combines them without
needing per-system score calibration.

The BM25 index is built per-call from chunks in Postgres scoped to the query (a single
document or all documents). For a research workload this is fine up to ~100k chunks;
beyond that, swap for an OpenSearch / Tantivy index.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select

from app.db import postgres, qdrant
from app.db.models import Chunk, Document
from app.llm import router as llm

_TOK_RE = re.compile(r"[A-Za-z0-9]+")
_STOP = set(
    """the a an and or of to in on for is are was were be been being this that these those
       it its as at by from with into about over under than then so but if not no yes can
       may might could should would will have has had do does did""".split()
)


def _tokenize(text: str) -> list[str]:
    return [w for w in (m.lower() for m in _TOK_RE.findall(text or "")) if w not in _STOP and len(w) > 1]


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    page: int
    title: str
    section: str | None
    kind: str
    text: str
    vector_score: float = 0.0
    bm25_rank: int = 0
    vector_rank: int = 0
    fused_score: float = 0.0


def _load_chunks(document_id: str | None) -> list[tuple[Chunk, str]]:
    """Return [(chunk, doc_title)] in deterministic order."""
    with postgres.session_scope() as s:
        stmt = select(Chunk, Document.title).join(Document, Document.id == Chunk.document_id)
        if document_id:
            stmt = stmt.where(Chunk.document_id == document_id)
        stmt = stmt.order_by(Chunk.document_id, Chunk.ord)
        rows = s.execute(stmt).all()
        # detach so callers can use after session closes
        return [(r[0], r[1]) for r in rows]


def _build_bm25(chunks: list[Chunk]):
    from rank_bm25 import BM25Okapi
    tokenized = [_tokenize(c.text) for c in chunks]
    # rank_bm25 chokes on empty corpora
    if not any(tokenized):
        return None, tokenized
    return BM25Okapi(tokenized), tokenized


def hybrid_search(
    query: str,
    *,
    top_k: int = 8,
    document_id: str | None = None,
    rrf_k: int = 60,
) -> list[Hit]:
    """Return top_k chunks fused from vector + BM25.

    Reciprocal Rank Fusion: score(c) = sum_i 1 / (rrf_k + rank_i(c))
    """
    qdrant.ensure_collection()

    # --- Vector branch ---
    vec = llm.embed([query], kind="query")[0]
    vfilt = {"document_id": document_id} if document_id else None
    v_hits = qdrant.search(vec, top_k=max(top_k * 3, 20), filt=vfilt)

    # --- Sparse branch ---
    chunks = _load_chunks(document_id)
    if not chunks:
        # No corpus — return what vector gave us, mapped into Hit shape
        return _vector_only(v_hits, top_k, rrf_k)

    bm25, _ = _build_bm25([c for c, _ in chunks])
    sparse_ranking: list[tuple[str, str, str]] = []  # (chunk_id, document_id, title)
    if bm25 is not None:
        scores = bm25.get_scores(_tokenize(query))
        order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
        for idx in order[: max(top_k * 3, 20)]:
            ch, title = chunks[idx]
            if scores[idx] <= 0:
                continue
            sparse_ranking.append((ch.id, ch.document_id, title))

    # --- Fuse ---
    fused: dict[str, Hit] = {}

    for rank, h in enumerate(v_hits, start=1):
        p = h.get("payload", {}) or {}
        cid = str(p.get("chunk_id") or h.get("id"))
        hit = Hit(
            chunk_id=cid,
            document_id=str(p.get("document_id") or ""),
            page=int(p.get("page") or 0),
            title=str(p.get("title") or ""),
            section=p.get("section"),
            kind=str(p.get("kind") or "text"),
            text=str(p.get("text") or ""),
            vector_score=float(h.get("score") or 0.0),
            vector_rank=rank,
        )
        fused[cid] = hit

    # ensure we have full text for any chunk only matched by BM25
    chunk_index = {c.id: (c, t) for c, t in chunks}
    for rank, (cid, doc_id, title) in enumerate(sparse_ranking, start=1):
        if cid in fused:
            fused[cid].bm25_rank = rank
            continue
        entry = chunk_index.get(cid)
        if entry is None:
            continue
        ch, _ = entry
        fused[cid] = Hit(
            chunk_id=cid,
            document_id=doc_id,
            page=ch.page,
            title=title,
            section=ch.section,
            kind=ch.kind,
            text=ch.text[:600],
            bm25_rank=rank,
        )

    for hit in fused.values():
        s = 0.0
        if hit.vector_rank:
            s += 1.0 / (rrf_k + hit.vector_rank)
        if hit.bm25_rank:
            s += 1.0 / (rrf_k + hit.bm25_rank)
        hit.fused_score = s

    ranked = sorted(fused.values(), key=lambda h: h.fused_score, reverse=True)[:top_k]

    # If the scoped search came back thin, fall back to global for the missing slots
    if document_id and len(ranked) < top_k:
        try:
            extra = hybrid_search(query, top_k=top_k - len(ranked), document_id=None)
            seen = {h.chunk_id for h in ranked}
            for e in extra:
                if e.chunk_id not in seen:
                    ranked.append(e)
                    if len(ranked) >= top_k:
                        break
        except Exception as e:
            logger.debug("global fallback failed: {}", e)

    return ranked


def _vector_only(v_hits: list[dict], top_k: int, rrf_k: int = 60) -> list[Hit]:
    out: list[Hit] = []
    for rank, h in enumerate(v_hits[:top_k], start=1):
        p = h.get("payload", {}) or {}
        out.append(Hit(
            chunk_id=str(p.get("chunk_id") or h.get("id")),
            document_id=str(p.get("document_id") or ""),
            page=int(p.get("page") or 0),
            title=str(p.get("title") or ""),
            section=p.get("section"),
            kind=str(p.get("kind") or "text"),
            text=str(p.get("text") or ""),
            vector_score=float(h.get("score") or 0.0),
            vector_rank=rank,
            fused_score=1.0 / (rrf_k + rank),
        ))
    return out
