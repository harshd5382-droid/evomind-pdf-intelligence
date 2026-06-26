"""Memory store — embed-on-write, cosine-search-on-read.

Why brute-force cosine instead of Qdrant?

In zero-infra mode, Qdrant runs in-process (`_MemoryStore`) and is wired to a
single collection of paper chunks with a fixed dim. Memories are smaller in
volume (a few thousand at most for a serious researcher) and the brute-force
NumPy path is sub-millisecond at that scale. Keeping them in SQLite/Postgres
also means a single `pg_dump` (or sqlite copy) is a complete export of the
agent's mind — chunks + memories + identity. That portability matters for a
project whose goal is a continuous identity.

If the user's corpus ever grows past ~50k memories we'll switch to a real
vector index, but we'll be honest about the threshold rather than premature.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.db import postgres
from app.db.models import Memory
from app.llm import router as llm
from app.llm.router import purpose

# Cache of (memory_id -> (embedding, content, layer, importance, source_kind, source_id, created_at))
# Rebuilt lazily on first search; invalidated on add. The cache is just an
# acceleration — every memory's embedding also lives in the DB column.
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_cache_dirty = True


@dataclass
class MemoryHit:
    id: str
    content: str
    layer: str
    importance: float
    source_kind: str | None
    source_id: str | None
    score: float
    created_at: datetime


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def _embed_one(text: str, *, kind: str = "passage") -> list[float] | None:
    """Embed a single string. Returns None on failure (caller decides
    whether to insert the memory anyway with a missing embedding)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        with purpose(f"memory:{kind}"):
            vecs = llm.embed([text], kind=kind)
        if vecs and isinstance(vecs[0], list) and vecs[0]:
            return vecs[0]
    except Exception as e:
        logger.warning("memory: embed failed ({}): {}", kind, e)
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0; na = 0.0; nb = 0.0
    for x, y in zip(a, b):
        dot += x * y; na += x * x; nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _batch_cosine(qv: list[float], vecs: list[list[float] | None]) -> list[float]:
    """Cosine similarity of `qv` against many vectors at once.

    Uses numpy for a single matrix op (much faster than the Python loop once the
    memory cache grows past a few hundred items); falls back to the scalar
    implementation if numpy is unavailable. Dim-mismatched / missing vectors
    score 0.0, matching `_cosine`'s contract.
    """
    if not vecs:
        return []
    try:
        import numpy as np

        q = np.asarray(qv, dtype="float32")
        qn = float(np.linalg.norm(q))
        res = [0.0] * len(vecs)
        if qn == 0.0:
            return res
        dim = q.shape[0]
        rows, idx = [], []
        for i, v in enumerate(vecs):
            if v is not None and len(v) == dim:
                rows.append(v); idx.append(i)
        if rows:
            mat = np.asarray(rows, dtype="float32")
            norms = np.linalg.norm(mat, axis=1)
            norms[norms == 0.0] = 1.0
            sims = (mat @ q) / (norms * qn)
            for j, i in enumerate(idx):
                res[i] = float(sims[j])
        return res
    except Exception:
        return [_cosine(qv, v) if v else 0.0 for v in vecs]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_memory(
    content: str,
    *,
    layer: str = "long",
    tags: list[str] | None = None,
    importance: float = 0.5,
    source_kind: str | None = None,
    source_id: str | None = None,
) -> str | None:
    """Insert a memory. Embeds the content (best-effort) and returns the new id.

    Returns None on failure. Idempotent on (source_kind, source_id) — if a
    memory with the same source already exists, this is a no-op so we don't
    double-store the same insight every time the autopilot revisits it.
    """
    global _cache_dirty
    content = (content or "").strip()
    if not content:
        return None

    # Idempotency on source identity
    if source_kind and source_id:
        try:
            with postgres.session_scope() as s:
                existing = s.execute(
                    select(Memory.id)
                    .where(Memory.source_kind == source_kind, Memory.source_id == source_id)
                    .limit(1)
                ).scalar_one_or_none()
            if existing:
                return existing
        except Exception as e:
            logger.debug("memory: dedup check failed: {}", e)

    embedding = _embed_one(content, kind="passage")

    try:
        with postgres.session_scope() as s:
            m = Memory(
                layer=layer, content=content[:8000],
                tags=tags or [], importance=float(importance),
                source_kind=source_kind, source_id=source_id,
                embedding=embedding,
            )
            s.add(m)
            s.flush()
            mid = m.id
        with _cache_lock:
            _cache_dirty = True
        return mid
    except Exception as e:
        logger.warning("memory: add failed: {}", e)
        return None


def _refresh_cache() -> None:
    """Reload all memories with embeddings into the in-process cache."""
    global _cache, _cache_dirty
    try:
        with postgres.session_scope() as s:
            rows = s.query(Memory).all()
            new_cache: dict[str, dict] = {}
            for m in rows:
                if not m.embedding:
                    continue
                new_cache[m.id] = {
                    "id": m.id,
                    "content": m.content,
                    "layer": m.layer,
                    "importance": m.importance or 0.0,
                    "source_kind": m.source_kind,
                    "source_id": m.source_id,
                    "created_at": m.created_at,
                    "embedding": m.embedding,
                }
        with _cache_lock:
            _cache = new_cache
            _cache_dirty = False
        logger.debug("memory: cache rebuilt ({} embedded memories)", len(new_cache))
    except Exception as e:
        logger.warning("memory: cache rebuild failed: {}", e)


def search_memories(
    query: str,
    *,
    k: int = 5,
    min_score: float = 0.25,
    layers: list[str] | None = None,
) -> list[MemoryHit]:
    """Return the top-K memories most semantically relevant to `query`.

    Falls back gracefully to recency if embedding the query fails or the
    cache has no embedded items.
    """
    if _cache_dirty:
        _refresh_cache()
    with _cache_lock:
        items = list(_cache.values())

    if not items:
        return []

    qv = _embed_one(query, kind="query")
    # If we couldn't embed the query, fall back to importance-weighted recency.
    if qv is None:
        items.sort(key=lambda m: (m["importance"], m["created_at"]), reverse=True)
        sliced = items[:k]
        return [MemoryHit(
            id=m["id"], content=m["content"], layer=m["layer"],
            importance=m["importance"], source_kind=m["source_kind"],
            source_id=m["source_id"], score=0.0, created_at=m["created_at"],
        ) for m in sliced if (not layers or m["layer"] in layers)]

    candidates = [m for m in items if not layers or m["layer"] in layers]
    sims = _batch_cosine(qv, [m["embedding"] for m in candidates])
    scored: list[tuple[float, dict]] = []
    for m, sim in zip(candidates, sims):
        # Bias: more important memories get a small boost. Caps total at 1.
        boost = 0.10 * float(m["importance"] or 0.0)
        score = min(1.0, sim + boost)
        if score >= min_score:
            scored.append((score, m))
    scored.sort(key=lambda t: t[0], reverse=True)
    out: list[MemoryHit] = []
    for score, m in scored[:k]:
        out.append(MemoryHit(
            id=m["id"], content=m["content"], layer=m["layer"],
            importance=m["importance"], source_kind=m["source_kind"],
            source_id=m["source_id"], score=score, created_at=m["created_at"],
        ))
    return out


def backfill_embeddings(batch: int = 32) -> int:
    """Embed any memory rows that don't yet have an embedding. Returns
    the number of rows updated. Cheap to call on startup."""
    updated = 0
    try:
        with postgres.session_scope() as s:
            todo = (
                s.query(Memory)
                .filter(Memory.embedding.is_(None))
                .order_by(Memory.created_at.desc())
                .limit(batch)
                .all()
            )
        if not todo:
            return 0
        # Batched embed for efficiency.
        try:
            with purpose("memory:backfill"):
                vecs = llm.embed([m.content for m in todo], kind="passage")
        except Exception as e:
            logger.warning("memory: backfill embed failed: {}", e)
            return 0

        with postgres.session_scope() as s:
            for m, v in zip(todo, vecs):
                row = s.get(Memory, m.id)
                if row is None or not v:
                    continue
                row.embedding = list(v)
                updated += 1

        if updated:
            global _cache_dirty
            with _cache_lock:
                _cache_dirty = True
            logger.info("memory: backfilled {} embeddings", updated)
    except Exception as e:
        logger.warning("memory: backfill pass failed: {}", e)
    return updated


def memory_stats() -> dict[str, Any]:
    try:
        with postgres.session_scope() as s:
            total = s.query(Memory).count()
            embedded = s.query(Memory).filter(Memory.embedding.isnot(None)).count()
            by_kind: dict[str, int] = {}
            for k, in s.query(Memory.source_kind).all():
                by_kind[k or "manual"] = by_kind.get(k or "manual", 0) + 1
        return {
            "total": total, "embedded": embedded,
            "pending": max(0, total - embedded),
            "by_source": by_kind,
        }
    except Exception as e:
        logger.warning("memory: stats failed: {}", e)
        return {"total": 0, "embedded": 0, "pending": 0, "by_source": {}}
