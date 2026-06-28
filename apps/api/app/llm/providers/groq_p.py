from __future__ import annotations

from app.core.config import get_settings
from app.llm.base import LLMProvider, LLMResult


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self) -> None:
        self.s = get_settings()
        from openai import OpenAI
        self.client = OpenAI(
            api_key=self.s.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        ) if self.s.groq_api_key else None

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 1500,
        json_mode: bool = False,
    ) -> LLMResult:
        if self.client is None:
            raise RuntimeError("GROQ_API_KEY is not configured")
        kwargs: dict = {
            "model": self.s.groq_model,
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
        return LLMResult(text=text, model=self.s.groq_model, usage=usage)
