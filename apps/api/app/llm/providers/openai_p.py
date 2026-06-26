from __future__ import annotations

from app.core.config import get_settings
from app.llm.base import EmbeddingProvider, LLMProvider, LLMResult


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        self.s = get_settings()
        from openai import OpenAI
        self.client = OpenAI(api_key=self.s.openai_api_key) if self.s.openai_api_key else None

    def complete(self, system: str, user: str, *, temperature: float = 0.4, max_tokens: int = 1500, json_mode: bool = False) -> LLMResult:
        if self.client is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        kwargs: dict = {
            "model": self.s.openai_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if resp.usage else None
        return LLMResult(text=text, model=self.s.openai_model, usage=usage)


class OpenAIEmbeddings(EmbeddingProvider):
    name = "openai"

    def __init__(self) -> None:
        self.s = get_settings()
        from openai import OpenAI
        self.client = OpenAI(api_key=self.s.openai_api_key) if self.s.openai_api_key else None
        # text-embedding-3-small is 1536 dims
        self.dim = 1536

    def embed(self, texts: list[str], *, kind: str = "passage") -> list[list[float]]:
        # OpenAI embedding models don't distinguish query/passage; flag accepted for uniformity.
        if self.client is None:
            raise RuntimeError("OPENAI_API_KEY is not configured for embeddings")
        resp = self.client.embeddings.create(model=self.s.openai_embedding_model, input=texts)
        self._last_usage = resp.usage.model_dump() if resp.usage else None
        return [d.embedding for d in resp.data]

    def usage(self) -> dict | None:
        return getattr(self, "_last_usage", None)
