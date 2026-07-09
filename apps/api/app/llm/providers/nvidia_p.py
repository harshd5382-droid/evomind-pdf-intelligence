"""NVIDIA NIM provider — uses build.nvidia.com's OpenAI-compatible endpoint.

Why a dedicated provider rather than reusing the OpenAI one:
- Model-specific "thinking" / reasoning knobs vary by model family and live in
  `extra_body.chat_template_kwargs`. Encoding that here keeps callers ignorant.
- Usage is reported correctly under the `nvidia` provider in the dashboard.
- We deliberately skip `response_format={"type": "json_object"}` because not every
  NIM model accepts it. We rely on the prompt instruction + the tolerant JSON
  parser in `app.llm.router.complete_json`.
"""
from __future__ import annotations

from loguru import logger

from app.core.config import get_settings
from app.llm.base import EmbeddingProvider, LLMProvider, LLMResult


def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc) or ""
    if "429" in msg or "Too Many Requests" in msg:
        return True
    cls = type(exc).__name__
    if cls == "RateLimitError":
        return True
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 429:
        return True
    return False


def _is_auth_error(exc: BaseException) -> bool:
    """True when NVIDIA rejected the credentials (HTTP 401/403), as opposed to a
    transient error. NIM answers a bad/expired key with 403 'Authorization failed'
    and a missing/wrong-scoped one with 401."""
    cls = type(exc).__name__
    if cls in ("AuthenticationError", "PermissionDeniedError"):
        return True
    status = getattr(exc, "status_code", None)
    resp = getattr(exc, "response", None)
    resp_status = getattr(resp, "status_code", None) if resp is not None else None
    if status in (401, 403) or resp_status in (401, 403):
        return True
    msg = str(exc) or ""
    return "401" in msg or "403" in msg or "Authorization failed" in msg


def _reraise(exc: Exception):
    """Re-raise, but turn an opaque provider auth failure into an actionable one.

    A raw `403 Forbidden` from the OpenAI-compatible client tells the operator
    nothing about *which* credential failed; surface the fix instead."""
    if _is_auth_error(exc):
        raise RuntimeError(
            "NVIDIA rejected the API key (HTTP 401/403 Authorization failed). Check "
            "that NVIDIA_API_KEY is valid, not expired, has no stray whitespace, and "
            "that your account can access the configured NVIDIA_MODEL. Get a fresh "
            f"free key at https://build.nvidia.com. Original error: {exc}"
        ) from exc
    raise exc


def _nvidia_keys(settings) -> list[str]:
    keys: list[str] = []
    for key in [settings.nvidia_api_key, settings.nvidia_api_key_backup]:
        if key and key not in keys:
            keys.append(key)
    for key in (settings.nvidia_api_key_backups or "").split(","):
        key = key.strip()
        if key and key not in keys:
            keys.append(key)
    return keys


class NvidiaProvider(LLMProvider):
    name = "nvidia"

    def __init__(self) -> None:
        self.s = get_settings()
        from openai import OpenAI  # NIM is OpenAI-compatible
        keys = _nvidia_keys(self.s)
        self._model = self.s.nvidia_model
        self.clients = []
        for idx, key in enumerate(keys):
            self.clients.append((
                OpenAI(
                    base_url=self.s.nvidia_base_url,
                    api_key=key,
                    timeout=float(self.s.nvidia_chat_timeout),
                    max_retries=2,
                ),
                "primary" if idx == 0 else f"backup-{idx}",
            ))
        if not self.clients:
            return

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 1500,
        json_mode: bool = False,
    ) -> LLMResult:
        if not self.clients:
            raise RuntimeError("NVIDIA_API_KEY is not configured")

        prompt_user = user
        if json_mode:
            prompt_user += "\n\nReturn ONLY a valid JSON object. No prose, no markdown fencing."

        kwargs: dict = {
            "model": self.s.nvidia_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt_user},
            ],
            "temperature": temperature,
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "stream": False,
            "timeout": float(self.s.nvidia_chat_timeout),
        }

        extra_body = self._extra_body_for(self.s.nvidia_model, self.s.nvidia_thinking, self.s.nvidia_reasoning_effort)
        if extra_body:
            kwargs["extra_body"] = extra_body

        last_exc: Exception | None = None
        for idx, (client, label) in enumerate(self.clients):
            try:
                if idx > 0:
                    logger.warning("NVIDIA chat: retrying on {} key after rate-limit", label)
                resp = client.chat.completions.create(**kwargs)
                choice = resp.choices[0]
                text = (choice.message.content or "").strip()

                # Some thinking models put the final answer in `content` and the chain-of-thought in
                # `reasoning_content`; we discard the reasoning. If `content` is empty (rare),
                # fall back to reasoning_content so the call isn't lost.
                if not text:
                    reasoning = getattr(choice.message, "reasoning_content", None)
                    if reasoning:
                        text = str(reasoning).strip()

                usage = resp.usage.model_dump() if resp.usage else None
                return LLMResult(text=text, model=self._model, usage=usage)
            except Exception as e:
                last_exc = e
                if idx < len(self.clients) - 1 and _is_rate_limit_error(e):
                    continue
                _reraise(e)
        if last_exc is not None:
            _reraise(last_exc)
        raise RuntimeError("NVIDIA chat failed without a response")

    @staticmethod
    def _extra_body_for(model: str, thinking: bool, reasoning_effort: str) -> dict | None:
        """Map our generic `thinking` flag onto each model family's vendor knobs.

        Based on the templates published at build.nvidia.com:
        - DeepSeek v4 / R1: `chat_template_kwargs.thinking` + `reasoning_effort`
        - Z-AI GLM: `chat_template_kwargs.enable_thinking` (+ `clear_thinking`)
        - NVIDIA Nemotron: `chat_template_kwargs.enable_thinking` (+ `reasoning_budget`)
        - Google Gemma: `chat_template_kwargs.enable_thinking`
        Everything else: no extra body.
        """
        m = (model or "").lower()
        if "deepseek-v4" in m or "deepseek-r1" in m:
            ckw: dict = {"thinking": bool(thinking)}
            if thinking and reasoning_effort:
                ckw["reasoning_effort"] = reasoning_effort
            return {"chat_template_kwargs": ckw}
        if "glm" in m:
            return {"chat_template_kwargs": {"enable_thinking": bool(thinking), "clear_thinking": False}}
        if "nemotron" in m:
            body: dict = {"chat_template_kwargs": {"enable_thinking": bool(thinking)}}
            if thinking:
                body["reasoning_budget"] = 16384
            return body
        if "gemma" in m:
            return {"chat_template_kwargs": {"enable_thinking": bool(thinking)}}
        return None


class NvidiaEmbeddings(EmbeddingProvider):
    """NVIDIA NIM embeddings via OpenAI-compatible /v1/embeddings.

    Default model `nvidia/nv-embedqa-e5-v5` is retrieval-tuned and distinguishes
    `query` vs `passage` input types — using the right one boosts recall meaningfully.
    """
    name = "nvidia"

    # Known dims for the NIM retrieval embedders. If the user picks an unknown
    # model we leave the default 1024 — the first call will throw if it's wrong
    # and they'll see a clear error.
    _DIMS = {
        "nvidia/nv-embedqa-e5-v5": 1024,
        "nvidia/nv-embedqa-mistral-7b-v2": 4096,
        "nvidia/nv-embed-v1": 4096,
        "snowflake/arctic-embed-l": 1024,
        "baai/bge-m3": 1024,
    }

    def __init__(self) -> None:
        self.s = get_settings()
        from openai import OpenAI
        keys = _nvidia_keys(self.s)
        self.clients = [
            (
                OpenAI(
                    base_url=self.s.nvidia_base_url,
                    api_key=key,
                    timeout=float(self.s.nvidia_embed_timeout),
                    max_retries=0,
                ),
                "primary" if idx == 0 else f"backup-{idx}",
            )
            for idx, key in enumerate(keys)
        ]
        self.dim = self._DIMS.get(self.s.nvidia_embedding_model, 1024)
        self._last_usage: dict | None = None

    def embed(self, texts: list[str], *, kind: str = "passage") -> list[list[float]]:
        if not self.clients:
            raise RuntimeError("NVIDIA_API_KEY is not configured for embeddings")
        if not texts:
            return []
        input_type = "query" if kind == "query" else "passage"
        last_exc: Exception | None = None
        resp = None
        for idx, (client, label) in enumerate(self.clients):
            try:
                if idx > 0:
                    logger.warning("NVIDIA embeddings: retrying on {} key after rate-limit", label)
                resp = client.embeddings.create(
                    model=self.s.nvidia_embedding_model,
                    input=texts,
                    extra_body={"input_type": input_type, "truncate": "END"},
                    timeout=float(self.s.nvidia_embed_timeout),
                )
                break
            except Exception as e:
                last_exc = e
                if idx < len(self.clients) - 1 and _is_rate_limit_error(e):
                    continue
                _reraise(e)
        if resp is None:
            if last_exc is not None:
                _reraise(last_exc)
            raise RuntimeError("NVIDIA embeddings failed without a response")
        if resp.usage:
            try:
                u = resp.usage.model_dump()
            except Exception:
                u = {"prompt_tokens": getattr(resp.usage, "prompt_tokens", 0)}
            self._last_usage = u
        # If the model returned a different dim than we expected, update so qdrant init matches
        first = resp.data[0].embedding if resp.data else []
        if first and len(first) != self.dim:
            self.dim = len(first)
        return [d.embedding for d in resp.data]

    def usage(self) -> dict | None:
        return self._last_usage
