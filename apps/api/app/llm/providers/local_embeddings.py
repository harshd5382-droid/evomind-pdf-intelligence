from __future__ import annotations

from threading import Lock

from app.llm.base import EmbeddingProvider

_lock = Lock()


class LocalEmbeddings(EmbeddingProvider):
    """sentence-transformers all-MiniLM-L6-v2 — 384 dim, fast, runs on CPU."""
    name = "local"
    dim = 384
    _model = None

    def _load(self):
        if LocalEmbeddings._model is None:
            with _lock:
                if LocalEmbeddings._model is None:
                    from sentence_transformers import SentenceTransformer
                    LocalEmbeddings._model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        return LocalEmbeddings._model

    def embed(self, texts: list[str], *, kind: str = "passage") -> list[list[float]]:
        # all-MiniLM doesn't distinguish query vs passage; flag is accepted for API uniformity.
        m = self._load()
        vecs = m.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vecs.tolist()
