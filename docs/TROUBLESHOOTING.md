# Troubleshooting

Common failure modes and how to fix them. Grouped by symptom.

---

## Embedding dimension mismatch after switching embedders

**Symptom** — after changing `EMBEDDING_PROVIDER` (or `NVIDIA_EMBEDDING_MODEL`),
ingestion or search fails with a Qdrant vector-dimension error, e.g. *"Vector
dimension error: expected 384, got 1024"*.

**Cause** — the Qdrant collection is created once with the embedder's dimension
and is immutable. Different embedders emit different-width vectors, so an
existing collection can't accept vectors from a new embedder:

| Embedder                              | Dim  |
|---------------------------------------|------|
| `local` (all-MiniLM-L6-v2)            | 384  |
| `nvidia` (nv-embedqa-e5-v5)           | 1024 |
| `nvidia` (nv-embedqa-mistral-7b-v2)   | 4096 |
| `openai` (text-embedding-3-small)     | 1536 |

**Fix** — either revert `EMBEDDING_PROVIDER`/model to what the collection was
built with, **or** recreate the collection and re-embed:

```bash
# Drops and recreates the Qdrant collection at the new dimension.
# NOTE: existing embeddings are lost — re-ingest or re-run the cycle to refill.
curl -X POST http://localhost:8000/api/admin/reset-vector-store \
  -H "X-API-Key: $API_KEY"   # only needed when AUTH_ENABLED=true
```

Do **not** mix embedders across a single corpus — retrieval quality collapses
when query and passage vectors come from different models.

---

## Free-tier (NVIDIA NIM) timeouts and 429s

**Symptom** — LLM calls hang, then fail with a timeout; or you see repeated
`429 Too Many Requests` in the logs, and questions stay `unresolved`.

**Cause** — the NVIDIA build.nvidia.com free tier is rate-limited (~40 req/min)
and individual calls can be slow, especially with reasoning enabled.

**Fixes**

- Keep `INGEST_WORKERS` low (≤ 2 on the free tier; the hard ceiling is 8). Each
  ingest makes ~2 LLM calls, so more workers just trip the rate limit faster.
- The provider router already retries with backoff and, if configured, trips over
  to `FALLBACK_PROVIDER` (default `ollama`) after persistent 429s. Set up Ollama
  locally to ride out throttling — see `OLLAMA_SETUP.md`.
- If calls hang rather than 429, they're bounded by `NVIDIA_CHAT_TIMEOUT`
  (default 60s) and `NVIDIA_EMBED_TIMEOUT` (30s). Lower these to fail fast, or
  raise them only if your provider is genuinely slow.
- Turn off `NVIDIA_THINKING` / lower `NVIDIA_REASONING_EFFORT` to cut per-call
  latency and token spend.

---

## `403 Forbidden` / `Authorization failed` on LLM calls

**Symptom** — ingestion succeeds (the document is detected, parsed, and chunked),
but the pipeline stalls at question generation. The logs show every LLM request
failing with `403 Forbidden` / `Authorization failed`, so no questions, feed
entries, or knowledge-graph nodes are produced and dashboard metrics stay at zero.

**Cause** — this 403 comes from the **LLM provider (NVIDIA NIM), not from
EvoMind's own auth.** It means the `NVIDIA_API_KEY` in your `.env` is present but
being *rejected* — expired, revoked, mistyped, or carrying stray whitespace — or
your account can't access the configured `NVIDIA_MODEL`. Ingestion works because
PDF parsing and (with `EMBEDDING_PROVIDER=local`) embedding don't call the chat
LLM; question generation is the first step that does, which is why it stops there.

> A *missing* key surfaces differently — `RuntimeError: NVIDIA_API_KEY is not
> configured` — so a 403 specifically means a key is set and refused.

**Fixes**

- Get a fresh key at https://build.nvidia.com (free-tier keys rotate/expire) and
  paste it into `NVIDIA_API_KEY` with no leading/trailing spaces or newline. It is
  used for both `PRIMARY_PROVIDER=nvidia` and `EMBEDDING_PROVIDER=nvidia`.
- Confirm your account can access the model in `NVIDIA_MODEL`.
- Verify the key independently of EvoMind, straight against the NIM endpoint:

  ```bash
  curl https://integrate.api.nvidia.com/v1/models \
    -H "Authorization: Bearer $NVIDIA_API_KEY"
  ```

  A 403 here confirms the key/account is the problem, not EvoMind.
- To run without a NIM key, point `PRIMARY_PROVIDER` at a local Ollama model (see
  `OLLAMA_SETUP.md`) or another provider you hold a valid key for, and set
  `EMBEDDING_PROVIDER=local` for offline, key-free embeddings.

Once the key is valid, the feed / questions / graph populate on the next research
cycle. (Note this is distinct from the `401` below, which is EvoMind's *own*
inbound auth rejecting a request to a mutating endpoint.)

---

## `pg_dump not found` when taking a backup

**Symptom** — `POST /api/backup/now` (or the scheduled `daily-backup`) returns
`{"ok": false, "error": "pg_dump not found on PATH"}`.

**Cause** — Postgres backups shell out to `pg_dump`, which isn't part of the API
image or a bare `pip install`. (SQLite deployments use an online `.backup()` and
are unaffected.)

**Fix** — install the Postgres client tools wherever the API process runs:

```bash
# Debian/Ubuntu (and most API container base images)
apt-get update && apt-get install -y postgresql-client

# macOS
brew install libpq && brew link --force libpq

# Alpine
apk add postgresql-client
```

Match the client major version to your server (16) to avoid version-skew
warnings. Verify with `pg_dump --version`.

---

## `401 Unauthorized` on mutating endpoints

**Symptom** — `POST`/`DELETE` calls (upload, solve, run-cycle, chat, feedback,
admin routes) return `401 missing or invalid API key`, or `503 auth_enabled is
true but no api_keys are configured`.

**Cause** — `AUTH_ENABLED=true` is set but the request carries no valid key.
Mutating and admin routes require a key; read-only routes (`GET`) do not.

**Fix** — send the key on every mutating request, as either header:

```
Authorization: Bearer <key>
X-API-Key: <key>
```

The key must appear in the comma-separated `API_KEYS` setting. If you enabled
auth but left `API_KEYS` empty, the API fails closed with a 503 by design — set
at least one key. When `AUTH_ENABLED=false` (the default) no key is needed.

> The web UI does not yet attach an API key to its requests, so enabling auth
> will break UI-driven actions (solve, chat, upload). Run with auth in
> API-only/proxied deployments, or put the whole stack behind your own
> authenticating reverse proxy.

---

## `429 Too Many Requests` from the API itself

**Symptom** — requests fail with `429` even though the LLM provider is fine.

**Cause** — application-level rate limiting is active (`RATE_LIMIT_ENABLED=true`,
default). The default budget is `RATE_LIMIT_DEFAULT` (240/min per client IP),
with tighter limits on chat and upload.

**Fix** — raise the limits for load tests or trusted networks, or disable
entirely with `RATE_LIMIT_ENABLED=false`. The SSE stream (`/api/feed/stream`) is
exempt so long-lived reconnects aren't throttled.

---

## Can't reach Postgres / Neo4j / Qdrant / the API from another machine

**Symptom** — after `docker compose up`, connecting to `5432`, `7474`, `7687`,
`6333`, or `8000` from a different host is refused, though `localhost` works.

**Cause** — these ports are deliberately published on `127.0.0.1` only. The
datastores use dev-default credentials and must never be exposed off-host; the
API is reachable to the browser through the web service's same-origin `/api`
proxy, so its published port is for local access only.

**Fix** — this is intentional hardening, not a bug. To administer remotely, use
an SSH tunnel:

```bash
ssh -L 7474:127.0.0.1:7474 -L 8000:127.0.0.1:8000 user@server
```

The web UI on `:3000` remains reachable normally. If you truly need a datastore
exposed (e.g. an external BI tool), change its `ports:` mapping back to
`"5432:5432"` — and set a strong password first.

---

## Autopilot shows as disabled under Docker

**Symptom** — `GET /api/autopilot/status` reports `enabled: false` when running
via `docker compose`, and there's no in-process research loop.

**Cause** — this is by design. In the Docker/Celery topology, **Celery Beat is
the single scheduler**: it drives the same solve/seed/synthesise/hypothesise/
snapshot cadences as the in-process autopilot *and* uniquely owns daily backup
and answer-quality eval. Running both would double LLM spend on identical work,
so `AUTOPILOT_ENABLED` defaults to `false` in `docker-compose.yml`.

**Fix** — nothing needed; research still runs, driven by the `beat` + `worker`
services. Confirm the worker is processing tasks:

```bash
docker compose logs -f worker beat
```

The in-process autopilot remains the default for the no-Redis local path
(`uvicorn app.main:app`), where there is no Celery Beat.
