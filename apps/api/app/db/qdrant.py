"""Vector store wrapper.

Talks to a real Qdrant instance when QDRANT_URL is reachable. When the URL is
"memory://" or the connection fails, falls back to an in-process numpy-backed
store. Same call surface either way: ensure_collection / upsert_chunks /
search / reset_collection.
"""
from __future__ import annotations

import math
import threading
from typing import Iterable

from loguru import logger

from app.core.config import get_settings

_settings = get_settings()
_client = None  # type: ignore[var-annotated]
_mode: str = "qdrant"  # qdrant | memory


# ---------- in-memory store ----------
class _MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._collections: dict[str, dict] = {}  # name -> {"size": int, "points": {id: (vec, payload)}}

    def ensure(self, name: str, size: int) -> None:
        with self._lock:
            if name not in self._collections:
                self._collections[name] = {"size": size, "points": {}}
            elif self._collections[name]["size"] != size:
                raise RuntimeError(
                    f"In-memory collection '{name}' has dim={self._collections[name]['size']} but provider produced dim={size}. "
                    "Call /api/admin/reset-vector-store."
                )

    def reset(self, name: str, size: int) -> None:
        with self._lock:
            self._collections[name] = {"size": size, "points": {}}

    def upsert(self, name: str, points: list[tuple[str, list[float], dict]]) -> None:
        with self._lock:
            col = self._collections.setdefault(name, {"size": len(points[0][1]) if points else 0, "points": {}})
            for pid, vec, payload in points:
                col["points"][str(pid)] = (vec, payload or {})

    def search(self, name: str, vector: list[float], top_k: int, filt: dict | None) -> list[dict]:
        with self._lock:
            col = self._collections.get(name)
            if not col:
                return []
            results: list[tuple[float, str, dict]] = []
            for pid, (vec, payload) in col["points"].items():
                if filt and not all(payload.get(k) == v for k, v in filt.items()):
                    continue
                results.append((_cosine(vector, vec), pid, payload))
        results.sort(key=lambda r: r[0], reverse=True)
        return [{"id": pid, "score": float(s), "payload": payload} for s, pid, payload in results[:top_k]]

    def info_dim(self, name: str) -> int | None:
        with self._lock:
            col = self._collections.get(name)
            return col["size"] if col else None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0; na = 0.0; nb = 0.0
    for x, y in zip(a, b):
        dot += x * y; na += x * x; nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


_memory: _MemoryStore | None = None


# ---------- public surface ----------
def _decide_mode() -> str:
    url = _settings.qdrant_url or ""
    if url.startswith("memory://") or not url:
        return "memory"
    return "qdrant"


def client():
    """Return the Qdrant client when possible, else None (memory mode)."""
    global _client, _mode, _memory
    if _mode == "memory" and _memory is not None:
        return None
    if _client is not None:
        return _client

    if _decide_mode() == "memory":
        _mode = "memory"
        _memory = _MemoryStore()
        logger.info("Vector store: in-memory mode (QDRANT_URL={!r})", _settings.qdrant_url)
        return None

    try:
        from qdrant_client import QdrantClient
        c = QdrantClient(url=_settings.qdrant_url, timeout=2.0)
        # ping
        c.get_collections()
        _client = c
        _mode = "qdrant"
        return _client
    except Exception as e:
        logger.warning("Qdrant unreachable ({}); using in-memory vector store", e)
        _mode = "memory"
        _memory = _MemoryStore()
        return None


def ensure_collection() -> None:
    from app.llm.router import embedding_provider  # local import to avoid cycles
    expected_dim = embedding_provider().dim

    c = client()
    if c is None:  # memory mode
        assert _memory is not None
        _memory.ensure(_settings.qdrant_collection, expected_dim)
        return

    from qdrant_client.http import models as qm
    existing = {col.name for col in c.get_collections().collections}
    if _settings.qdrant_collection not in existing:
        c.create_collection(
            collection_name=_settings.qdrant_collection,
            vectors_config=qm.VectorParams(size=expected_dim, distance=qm.Distance.COSINE),
        )
        return

    info = c.get_collection(_settings.qdrant_collection)
    actual_dim = None
    try:
        actual_dim = int(info.config.params.vectors.size)  # type: ignore[attr-defined]
    except Exception:
        pass
    if actual_dim and actual_dim != expected_dim:
        raise RuntimeError(
            f"Qdrant collection '{_settings.qdrant_collection}' has dim={actual_dim} but the active embedding provider produces dim={expected_dim}. "
            "Either revert EMBEDDING_PROVIDER, or recreate via POST /api/admin/reset-vector-store."
        )


def reset_collection() -> None:
    from app.llm.router import embedding_provider
    expected_dim = embedding_provider().dim
    c = client()
    if c is None:
        assert _memory is not None
        _memory.reset(_settings.qdrant_collection, expected_dim)
        return
    from qdrant_client.http import models as qm
    try:
        c.delete_collection(_settings.qdrant_collection)
    except Exception:
        pass
    c.create_collection(
        collection_name=_settings.qdrant_collection,
        vectors_config=qm.VectorParams(size=expected_dim, distance=qm.Distance.COSINE),
    )


def upsert_chunks(points: Iterable[tuple[str, list[float], dict]]) -> None:
    pts = list(points)
    if not pts:
        return
    c = client()
    if c is None:
        assert _memory is not None
        _memory.upsert(_settings.qdrant_collection, pts)
        return
    from qdrant_client.http import models as qm
    batch = [qm.PointStruct(id=pid, vector=vec, payload=payload) for pid, vec, payload in pts]
    c.upsert(collection_name=_settings.qdrant_collection, points=batch)


def search(vector: list[float], top_k: int = 8, filt: dict | None = None) -> list[dict]:
    c = client()
    if c is None:
        assert _memory is not None
        return _memory.search(_settings.qdrant_collection, vector, top_k, filt)
    from qdrant_client.http import models as qm
    qfilter = None
    if filt:
        qfilter = qm.Filter(
            must=[qm.FieldCondition(key=k, match=qm.MatchValue(value=v)) for k, v in filt.items()]
        )
    res = c.search(
        collection_name=_settings.qdrant_collection,
        query_vector=vector,
        limit=top_k,
        query_filter=qfilter,
        with_payload=True,
    )
    return [{"id": str(p.id), "score": float(p.score), "payload": p.payload or {}} for p in res]


def mode() -> str:
    client()
    return _mode


def status() -> dict:
    c = client()
    if c is None:
        dim = _memory.info_dim(_settings.qdrant_collection) if _memory is not None else None
        return {
            "mode": "memory",
            "reachable": True,
            "collection": _settings.qdrant_collection,
            "dimension": dim,
            "error": None,
        }
    try:
        info = c.get_collection(_settings.qdrant_collection)
        dim = None
        try:
            dim = int(info.config.params.vectors.size)  # type: ignore[attr-defined]
        except Exception:
            pass
        return {
            "mode": "qdrant",
            "reachable": True,
            "collection": _settings.qdrant_collection,
            "dimension": dim,
            "error": None,
        }
    except Exception as exc:
        return {
            "mode": "qdrant",
            "reachable": False,
            "collection": _settings.qdrant_collection,
            "dimension": None,
            "error": str(exc),
        }
