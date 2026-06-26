from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Search candidates for the .env file: cwd, the api package root, the monorepo root.
# Note: depth differs between a checkout (.../apps/api/app/core/config.py) and the
# Docker image (/app/app/core/config.py), so guard each parent lookup against range.
_HERE = Path(__file__).resolve()
_PARENTS = _HERE.parents
_CANDIDATES = [Path.cwd() / ".env"]
for _i in (2, 3, 4):  # apps/api/.env, apps/.env, repo-root/.env (when present)
    if _i < len(_PARENTS):
        _CANDIDATES.append(_PARENTS[_i] / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=tuple(str(p) for p in _CANDIDATES if p.exists()) or (".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "EvoMind PDF Intelligence"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    # Emit logs as JSON (one object per line) — useful behind Loki/ELK in prod.
    log_json: bool = False
    # Expose a Prometheus /metrics endpoint and record LLM/HTTP metrics.
    metrics_enabled: bool = True

    # ─── Security ───────────────────────────────────────────────────────
    # Off by default so local/dev and the test suite are unaffected. When
    # enabled, mutating + admin endpoints require a Bearer token (or X-API-Key
    # header) present in `api_keys` (comma-separated).
    auth_enabled: bool = False
    api_keys: str = ""
    # CORS: comma-separated allowed origins. "*" allows any (dev convenience).
    cors_origins: str = "*"
    # Uploads: reject files larger than this (defence against disk-fill).
    max_upload_mb: int = 50
    # Rate limiting (slowapi). Generous defaults; disable for load tests.
    rate_limit_enabled: bool = True
    rate_limit_default: str = "240/minute"
    rate_limit_chat: str = "60/minute"
    rate_limit_upload: str = "60/minute"

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]

    # Storage
    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"

    # Postgres
    postgres_dsn: str = "postgresql+psycopg://evomind:evomind@localhost:5432/evomind"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "evomind_chunks"
    embedding_dim: int = 384

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "evomind123"

    # LLM Providers — set whichever you intend to use
    primary_provider: str = "nvidia"  # nvidia | anthropic | openai | gemini | ollama
    embedding_provider: str = "nvidia"  # nvidia | local | openai

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-7"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-pro"

    ollama_base_url: str = "http://localhost:11434"
    # Default chosen for 8 GB RAM machines. Qwen 2.5 7B is the strongest
    # general-purpose 7B on agentic JSON tasks (per Open LLM Leaderboard at
    # time of writing). It fits in ~4.4 GB at Q4_K_M, leaving room for the
    # OS + browser + our backend. On bigger machines, prefer qwen2.5:14b
    # or qwen2.5:32b. See OLLAMA_SETUP.md for the model tiers and tuning.
    ollama_model: str = "qwen2.5:7b-instruct-q4_K_M"
    # Cap context to save RAM. Our longest prompts are ~3K tokens; 4K leaves
    # margin without paying for the 32K window the model can do.
    ollama_num_ctx: int = 4096
    # Keep the model loaded between calls — first inference costs ~30 s for
    # the model load, subsequent calls reuse the loaded weights.
    ollama_keep_alive: str = "10m"
    ollama_timeout: float = 600.0  # CPU inference is slow; allow long calls

    # NVIDIA NIM (build.nvidia.com — OpenAI-compatible)
    nvidia_api_key: str | None = None
    nvidia_api_key_backup: str | None = None
    nvidia_api_key_backups: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Default chosen for reliability on free-tier accounts. DeepSeek v4 / GLM are
    # available via the same endpoint but may be tier-restricted or require streaming.
    nvidia_model: str = "meta/llama-3.3-70b-instruct"
    nvidia_embedding_model: str = "nvidia/nv-embedqa-e5-v5"
    # Enable model-side reasoning ("thinking") when the model supports it.
    nvidia_thinking: bool = False
    nvidia_reasoning_effort: str = "max"
    # Hard request timeouts in seconds — surface failures fast instead of hanging the worker.
    nvidia_chat_timeout: float = 60.0
    nvidia_embed_timeout: float = 30.0

    # In-process ingest worker pool size (used when Celery is unavailable).
    # Each ingest worker makes ~2 LLM calls per PDF (classify + seed questions).
    # On the NVIDIA free tier (~40 req/min), 2 workers leaves headroom for the
    # solver, identity, journal, and curiosity phases. Bump only on paid tiers.
    ingest_workers: int = 2

    # ─── Provider fallback (Ollama as safety net for NVIDIA throttling) ───
    # When the primary provider returns persistent 429s, the router auto-
    # switches to the fallback for `fallback_cooldown_sec` seconds, then
    # tries primary again. Set to "" to disable fallback entirely.
    fallback_provider: str = "ollama"
    fallback_cooldown_sec: int = 90        # how long to stay on fallback after a trip
    fallback_429_threshold: int = 3        # 429s in 60s window required to trip
    fallback_min_health_check_sec: int = 30  # how often to re-check fallback availability

    # When the ingest queue is deeper than this, the folder watcher pauses
    # picking up new PDFs. Lets the autopilot catch up on solving / synthesis
    # instead of starving them. 0 disables drain mode entirely.
    auto_ingest_drain_threshold: int = 50

    # PDF parser preference order
    parser_priority: str = "llamaparse,pymupdf,pdfplumber"
    llamaparse_api_key: str | None = None

    # Autonomy knobs
    questions_per_doc: int = 10
    recursion_depth: int = 3
    autonomy_level: str = "aggressive"  # cautious | balanced | aggressive
    creativity: float = 0.7
    confidence_threshold: float = 0.55

    # ─── Autopilot (in-process continuous research loop) ───
    # Runs inside the FastAPI process; no Celery / Redis required.
    autopilot_enabled: bool = True
    autopilot_solve_interval_sec: int = 45    # how often to drain open questions
    autopilot_solve_batch: int = 3            # questions per iteration (LLM calls = 2x this)
    autopilot_seed_interval_sec: int = 60     # how often to scan for unseeded docs
    autopilot_synthesis_interval_sec: int = 900   # 15 min — synthesise insights
    autopilot_hypothesis_interval_sec: int = 1800 # 30 min — generate hypotheses
    autopilot_score_interval_sec: int = 300       # 5 min — refresh intelligence snapshot
    autopilot_contradictions_interval_sec: int = 1200  # 20 min — scan for contradictions
    autopilot_journal_interval_sec: int = 1800         # 30 min — write a reflective journal entry
    autopilot_curiosity_interval_sec: int = 600        # 10 min — recompute knowledge gaps
    autopilot_curiosity_question_ratio: float = 0.4    # share of new questions seeded from gaps (0–1)

    # ─── Auto-ingest folder watcher ───
    # Drop PDFs (or whole folders of PDFs) into `auto_ingest_dir` and the API
    # will pick them up, ingest, seed questions, and the autopilot will reason
    # over them. No HTTP upload required.
    auto_ingest_enabled: bool = True
    auto_ingest_dir: str = "./data/dropbox"
    auto_ingest_interval_sec: int = 10        # scan cadence
    auto_ingest_stable_sec: float = 2.0       # mtime must be still for this long


@lru_cache
def get_settings() -> Settings:
    return Settings()
