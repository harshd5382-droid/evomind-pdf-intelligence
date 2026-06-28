"""Ollama provider — local inference safety net.

Used as the automatic fallback when the cloud primary (NVIDIA / OpenAI / …)
is throttled. Speed is bounded by the user's CPU; quality depends on the
chosen model. Tuned for an 8 GB RAM machine running Qwen 2.5 7B by default.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.llm.base import LLMProvider, LLMResult


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self) -> None:
        self.s = get_settings()

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 1500,
        json_mode: bool = False,
        **_extra,
    ) -> LLMResult:
        url = f"{self.s.ollama_base_url.rstrip('/')}/api/chat"
        # `num_ctx` and `keep_alive` are critical for low-RAM laptops:
        #   - num_ctx caps context window to save VRAM/RAM
        #   - keep_alive holds the model in memory between calls (saves ~30s reload)
        options: dict = {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": int(self.s.ollama_num_ctx),
        }
        payload: dict = {
            "model": self.s.ollama_model,
            "stream": False,
            "keep_alive": self.s.ollama_keep_alive,
            "options": options,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user + (
                    "\n\nReturn ONLY a valid JSON object. No prose, no markdown fencing."
                    if json_mode else ""
                )},
            ],
        }
        if json_mode:
            # Ollama's `format: json` constrains output to valid JSON via
            # grammar-constrained sampling. Reliable on Qwen 2.5 / Llama 3.x.
            payload["format"] = "json"

        try:
            with httpx.Client(timeout=float(self.s.ollama_timeout)) as c:
                r = c.post(url, json=payload)
                r.raise_for_status()
                data = r.json()
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Ollama unreachable at {self.s.ollama_base_url} — is the daemon running? "
                f"(`ollama serve` or the desktop app). Underlying error: {e}"
            )
        except httpx.HTTPStatusError as e:
            # Most common failure: model not pulled. Surface that clearly.
            body = e.response.text[:300] if e.response is not None else ""
            if "model" in body.lower() and "not found" in body.lower():
                raise RuntimeError(
                    f"Ollama doesn't have '{self.s.ollama_model}' pulled yet. "
                    f"Run: `ollama pull {self.s.ollama_model}`"
                )
            raise RuntimeError(f"Ollama HTTP {e.response.status_code if e.response else '?'}: {body}")

        text = (data.get("message", {}) or {}).get("content", "")
        # Ollama returns prompt_eval_count + eval_count for the last response.
        usage = {
            "input_tokens": int(data.get("prompt_eval_count") or 0),
            "output_tokens": int(data.get("eval_count") or 0),
        }
        return LLMResult(text=text, model=self.s.ollama_model, usage=usage)


def health_check(timeout_sec: float = 3.0) -> tuple[bool, str]:
    """Quick liveness probe — used by the router to decide whether
    falling back is even possible."""
    s = get_settings()
    try:
        with httpx.Client(timeout=timeout_sec) as c:
            r = c.get(f"{s.ollama_base_url.rstrip('/')}/api/tags")
            r.raise_for_status()
            tags = r.json().get("models", []) or []
            names = {m.get("name", "").split(":")[0] for m in tags}
            want = s.ollama_model.split(":")[0]
            if want and names and want not in names:
                # Daemon is up but model isn't pulled.
                return (False, f"daemon up, but '{s.ollama_model}' not pulled (run: ollama pull {s.ollama_model})")
            return (True, f"daemon up, {len(tags)} models available")
    except Exception as e:
        return (False, f"unreachable at {s.ollama_base_url}: {e}")
