from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResult:
    text: str
    model: str
    usage: dict | None = None


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, system: str, user: str, *, temperature: float = 0.4, max_tokens: int = 1500, json_mode: bool = False) -> LLMResult:
        ...


class EmbeddingProvider(ABC):
    name: str = "base"
    dim: int = 384

    @abstractmethod
    def embed(self, texts: list[str], *, kind: str = "passage") -> list[list[float]]:
        """Embed texts. `kind` is "passage" (default — for ingestion / stored docs)
        or "query" (for retrieval-time queries). Providers that don't distinguish
        may ignore the flag."""
        ...

    def usage(self) -> dict | None:
        """Return token usage from the most recent embed() call, if the provider tracks it."""
        return None
