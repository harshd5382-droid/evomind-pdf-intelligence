from __future__ import annotations

from app.core.config import get_settings
from app.llm.base import LLMProvider, LLMResult


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        self.s = get_settings()
        from anthropic import Anthropic  # lazy import
        self.client = Anthropic(api_key=self.s.anthropic_api_key) if self.s.anthropic_api_key else None

    def complete(self, system: str, user: str, *, temperature: float = 0.4, max_tokens: int = 1500, json_mode: bool = False) -> LLMResult:
        if self.client is None:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured")
        prompt_user = user
        if json_mode:
            prompt_user += "\n\nReturn ONLY a valid JSON object. No prose, no markdown fencing."
        msg = self.client.messages.create(
            model=self.s.anthropic_model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt_user}],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        return LLMResult(text=text, model=self.s.anthropic_model, usage={"input": msg.usage.input_tokens, "output": msg.usage.output_tokens})
