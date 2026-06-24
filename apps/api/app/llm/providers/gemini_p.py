from __future__ import annotations

from app.core.config import get_settings
from app.llm.base import LLMProvider, LLMResult


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        self.s = get_settings()
        if not self.s.gemini_api_key:
            self.model = None
            return
        import google.generativeai as genai
        genai.configure(api_key=self.s.gemini_api_key)
        self.model = genai.GenerativeModel(self.s.gemini_model)

    def complete(self, system: str, user: str, *, temperature: float = 0.4, max_tokens: int = 1500, json_mode: bool = False) -> LLMResult:
        if self.model is None:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        prompt = f"{system}\n\n{user}"
        if json_mode:
            prompt += "\n\nRespond with ONLY a valid JSON object."
        cfg = {"temperature": temperature, "max_output_tokens": max_tokens}
        resp = self.model.generate_content(prompt, generation_config=cfg)
        return LLMResult(text=resp.text or "", model=self.s.gemini_model)
