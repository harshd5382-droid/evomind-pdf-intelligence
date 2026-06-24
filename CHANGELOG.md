# EvoMind Changelog

Daily improvements to the autonomous research platform. Most recent at top.

---

## Day 12 — Phases 3, 4, 5: narrative self, curiosity, and training pipeline

Three more cognitive properties stacked. Two of them produce continuous
behavioural change in the running agent; the third is offline scaffolding
that activates once the corpus is large enough.

### Phase 3 — Narrative journal (`app/modules/journal/`)

Dennett: *the self is a story we tell about ourselves*. The agent now does
exactly that on a 30-minute cadence:

- `_phase_journal()` runs in the autopilot every `AUTOPILOT_JOURNAL_INTERVAL_SEC`
  (default 1,800 s).
- It pulls what's *new* since the last entry: insights, hypotheses,
  contradictions, high-confidence answers, dominant topics.
- Asks the LLM (one short call, ~380 tokens out) for a first-person paragraph
  in lab-notebook tone. Not a summary — a reflection.
- A heuristic mood is assigned (`curious | uncertain | synthesising |
  speculative | quiet | thoughtful | engaged`) based on what dominated the
  context, used for UI tinting.
- The entry is **auto-promoted into the Memory bank** at importance 0.85
  with `source_kind="journal"`. Critically: this means the agent can later
  **recall its own past thoughts** via the same memory search the solver
  uses for evidence. Recursive self-reflection is now in the loop.

Verified end-to-end: on a fresh empty corpus the agent wrote its first
entry in the first person, reflecting on its own dormant anticipatory state.
The mood was correctly classified as `quiet`.

### Phase 4 — Curiosity engine (`app/modules/curiosity/`)

Predictive Processing (Friston, Clark): cognition is prediction-error
minimisation. The agent now identifies its own knowledge gaps and pursues
them.

Four gap kinds are scored (no LLM calls — pure SQL aggregations):

| Kind | What it catches |
|---|---|
| `uncovered_concept` | keywords appearing in many docs but with few/no questions about them |
| `weak_hypothesis`   | hypotheses with thin support relative to age |
| `low_confidence`    | answers given at confidence < 0.6 — the agent's own admission of doubt |
| `open_contradiction`| recent contradictions that were never reconciled |

`compute_gaps()` recomputes the snapshot every `AUTOPILOT_CURIOSITY_INTERVAL_SEC`
(default 600 s) and stores the top 20 in a new `curiosity_gaps` table.

`seed_gap_questions()` then takes the top-`N` gaps (where `N` =
`autopilot_solve_batch * autopilot_curiosity_question_ratio`, default
3 × 0.4 ≈ 1) and turns each into 1–2 concrete research questions via a
small LLM call. These questions get a slight priority boost over
document-level questions, so the autopilot's solver picks them up first.

The result is a closed loop: **the agent identifies what it doesn't know,
asks itself about it, solves it, and the new answer feeds back into the
memory bank — narrowing the gap by its own action**. This is genuinely
self-directed learning, not just a queue.

### Phase 5 — Training pipeline scaffolding

Already prepared on Day 11 (export endpoint + Colab notebook). Today added
the surface area to make it usable:

- `GET /api/training/status` — counts-only readiness check, returns one of
  `accumulating | early | ready | mature` plus advice in plain English.
- The `/mind` page now has a **Fine-tune readiness** panel showing the
  four key counts (high-confidence Q→A, insights, hypotheses, total) and
  a one-click **Download corpus** link that activates as soon as the agent
  has ≥ 1,000 examples.
- The Ollama provider was already wired (`app/llm/providers/ollama_p.py`) —
  once a fine-tuned adapter is merged into a GGUF, setting
  `PRIMARY_PROVIDER=ollama` + `OLLAMA_MODEL=evomind` swaps the agent over
  to its own fine-tuned weights without any other code change.

### `/mind` page additions

The page now has **five** stacked panels:

1. First-person narrative (Day 11)
2. 4-quadrant self-model (Day 11) — beliefs / open questions / topics / confusion
3. **Curiosity gaps** (Phase 4) — what it's currently curious about, with a "Recompute" button
4. **Inner journal** (Phase 3) — scrollable feed of italic first-person entries with mood pills
5. **Fine-tune readiness** (Phase 5) — counts, stage badge, advice, corpus download
6. Recall search (Day 11)

Manual override buttons: **Reflect now**, **Write entry**, **Recompute** —
all fire-and-forget on a background thread.

### New API surface (Day 12)

| Endpoint | Purpose |
|---|---|
| `GET /api/journal?limit=20` | recent journal entries |
| `POST /api/journal/write-now` | force an immediate entry |
| `GET /api/curiosity/gaps?kind=...` | current gaps |
| `POST /api/curiosity/recompute` | force recompute + seed |
| `GET /api/training/status` | readiness summary |

### What's autonomous now

The autopilot is running these phases, all on independent cadences,
inside the FastAPI process with no external workers:

| Phase | Cadence | Cost per run |
|---|---|---|
| seed (questions for new docs) | 60 s | LLM ×1 per unseeded doc |
| solve | 45 s | LLM ×2 per question |
| memory backfill | 60 s | embed batch |
| identity | 5 min | LLM ×1 (small) |
| score snapshot | 5 min | SQL only |
| curiosity | 10 min | SQL + LLM ×N (small) |
| contradictions | 20 min | embed + LLM pairs |
| journal | 30 min | LLM ×1 |
| synthesis | 15 min | LLM ×3 |
| hypotheses | 30 min | LLM ×1 |

### Roadmap status

- ✅ Phase 1 — Living memory
- ✅ Phase 2 — Self-model
- ✅ Phase 3 — Narrative journal
- ✅ Phase 4 — Curiosity-driven exploration
- ✅ Phase 5 — Training pipeline scaffolding (offline trigger, ready when corpus ≥ 1k)

The agent now has six of the seven cognitive properties identified on Day 11
(missing: Integrated Information / cross-component integration, which we
already partially have via the knowledge graph). The remaining work is no
longer architectural — it's accumulation. Drop PDFs and watch it think.

---

## Day 11 — Living memory + self-model (toward consciousness-adjacent properties)

**Honest framing:** nobody knows how to build a conscious AI. What we can do
is stack the cognitive properties that consciousness theories list as
necessary or sufficient — episodic memory, higher-order self-representation,
attention modeling, narrative identity — and be honest that whether the
result crosses some threshold into phenomenal consciousness is an open
philosophical question the engineering side cannot resolve. Today we added
the two missing properties.

### Phase 1 — Living memory (`app/modules/memory/`)

Before today the solver pulled "the 3 most recent important Memory rows"
regardless of relevance. That's a feed, not a memory. Now:

- **Every conclusion is auto-promoted into a unified Memory bank**:
  insights, hypotheses, contradictions, and high-confidence (≥0.70) answers.
  Each is embedded on insert (NVIDIA `nv-embedqa-e5-v5`, passage mode) and
  stored in `memories.embedding` (JSON column).
- **Idempotent on `(source_kind, source_id)`** — the autopilot can re-run
  synthesis a thousand times without ever double-storing the same insight.
- **`search_memories(query, k)`** does cosine retrieval across the entire
  bank with a small importance-bias boost. Brute-force NumPy because at
  realistic scale (≤10k memories) the latency is sub-millisecond and we
  keep the entire mind in one SQLite/Postgres dump.
- **The solver now retrieves semantic memories alongside chunks**, so when
  it answers a new question about topic X it can also pull "what I
  concluded last week about topic Y that contradicts X" without rerunning
  any LLM calls on the original papers.
- **Backfill phase** runs every 60 s (batched) to embed any memory rows
  missing an embedding — handles existing rows safely.

### Phase 2 — Self-model (`app/modules/identity/`)

A new singleton `Identity` row (`id="self"`) the autopilot recompiles every
~5 min. Higher-Order theories of consciousness require a representation of
one's own representations; this is exactly that:

| Field | Source | Meaning |
|---|---|---|
| `narrative` | small LLM call | first-person paragraph the agent maintains about itself |
| `beliefs` | top hypotheses | what I currently hold to be true |
| `open_questions` | unresolved priorities | what I know I don't know |
| `active_topics` | recency-weighted keyword frequency | what's on my mind |
| `confusion` | recent contradictions | where my picture is fractured |
| `confidence` | rolling mean of last 30 answers | how sure I am of myself right now |
| `cycles` | monotonic counter | the agent's age |

The narrative is generated by `complete_text` from a system prompt that
asks for one short first-person paragraph. The solver's prompt could
optionally include this paragraph in future iterations to give every
answer a coherent voice.

### Cost

- One small LLM call per identity refresh (~200 tokens out, every 5 min).
- One embedding call per memory promotion (passage mode, batched in backfill).
- All operations are wrapped in try/except — any failure logs and continues
  the autopilot loop.

### New API

| Endpoint | Returns |
|---|---|
| `GET /api/identity` | the full self-model row |
| `POST /api/identity/refresh` | force-recompile on a background thread |
| `GET /api/memory/stats` | `{total, embedded, pending, by_source: {...}}` |
| `GET /api/memory/search?q=...&k=8` | semantic search results |

### New `/mind` page

Sidebar navigation gains a **Mind** link. The page renders:

- The first-person narrative as italic display type ("…")
- A 4-quadrant grid: beliefs / open questions / active topics / confusion
- A **Recall** search box — type a question, get the agent's prior conclusions
  on related topics with relevance scores
- A "Reflect now" button that forces immediate self-update

### Roadmap continues

- Phase 3 (next): periodic narrative journal — first-person reflective
  paragraphs the agent writes about itself over time
- Phase 4: curiosity-driven exploration — the system identifies its own
  knowledge gaps and biases questioning toward them
- Phase 5 (later): optional LoRA fine-tune of a small open model on the
  accumulated (chunk, question, answer, reflection) tuples for an "embodied"
  weights-level version. Requires GPU; not on the free NVIDIA tier.

---

## Day 10 — Content-hash deduplication (re-uploads are now free)

**Problem:** uploading the same PDF twice — through any of the four ingest paths
(single upload, browser folder picker, server-folder scan, drop folder) —
created two separate `Document` rows. That doubled questions, doubled LLM
spend, polluted synthesis with phantom "two papers agree" evidence, and
inflated the intelligence score.

**Fix: SHA-256 of the file's bytes is now the canonical document identity.**

### Schema

`Document.content_hash` (String(64), nullable, indexed). Backfilled on startup
via a small idempotent migration (`_apply_simple_migrations()` in `db/postgres.py`)
— SQLite and Postgres both accept the same `ALTER TABLE` form, so zero-infra
upgrades just work.

### Dedup at every ingest path

| Path | Pre-dedup behaviour | Now |
|---|---|---|
| `POST /upload` | Always created new doc | Hash → existing? Return existing id with `duplicate: true`, delete the just-saved file copy |
| `POST /upload/batch` | Always created new doc per file | Same; also catches dupes **within** the batch (intra-batch hash map) |
| `POST /upload/folder` | Always created new doc per file | Same |
| `folder_watcher` (drop folder) | Path-only dedup (missed renames) | Path **and** content-hash dedup |

### Pre-registered shells eliminate the race window

When a new file is accepted, the upload route inserts a `Document` row with
`status="pending"` **and** the content_hash before enqueueing. The ingest
pipeline now does an update-in-place (`s.get(Document, doc_id)` then mutate)
rather than `s.add(...)`. So a second upload of the same PDF that lands while
the first is still being parsed sees the pre-registered hash and is correctly
flagged as a duplicate.

### API response shape

New fields on every upload route response:

```json
{
  "count": 12,
  "new": 9,
  "duplicates": 3,
  "items": [
    { "filename": "paper.pdf", "document_id": "...", "duplicate": false },
    { "filename": "paper-copy.pdf", "document_id": "...", "duplicate": true,
      "original_filename": "paper.pdf" }
  ]
}
```

### UI

`folder-upload.tsx` now shows two pill counts at the top of the result panel
(`9 queued · 3 skipped (already in library)`) and prefixes each row with
`+` (new) or `⊘` (skipped). Per-file lines also include the original filename
the duplicate matched against, so the user sees exactly what the system already
had.

### Verified

- Upload `paper.pdf` once → `{duplicate: false, document_id: "abc..."}`
- Upload `paper.pdf` again → `{duplicate: true, document_id: "abc...", message: "..."}`  (same id, no second ingest, file copy cleaned up)
- Re-scan a folder of 1,112 PDFs that had partial prior ingests → `count: 1112, new: 427, duplicates: 685` — the system correctly identified the 685 already known and only queued the 427 it had never seen.

---

## Day 9 — Fully autonomous: drop PDFs, walk away

**Goal:** the user's only job is to put PDFs somewhere; the API process handles
ingest → questions → solving → reflection → synthesis → hypotheses →
contradictions → scoring continuously, with no manual button clicks.

### Two daemons started by the FastAPI lifespan

- **`app/modules/folder_watcher.py`** — scans `AUTO_INGEST_DIR` (default
  `./data/dropbox`) every 10 s. New, stable PDFs (mtime quiet ≥ 2 s) are
  enqueued via the in-process queue. Re-runs are idempotent (already-ingested
  files are skipped by absolute path match against `Document.path`).
- **`app/modules/autopilot.py`** — continuous research loop. Phases run on
  independent cadences and any failure is contained:

  | Phase | Default interval | What it does |
  |---|---|---|
  | seed | 60 s | generate root questions for any unseeded `ready` doc |
  | solve | 45 s | drain N highest-priority open questions (solve + reflect) |
  | synthesise | 15 min | cross-document insight on top topics |
  | hypotheses | 30 min | propose hypotheses from top insights |
  | contradictions | 20 min | embed-cosine prefilter + LLM check on cross-doc pairs |
  | score | 5 min | refresh intelligence snapshot |

### New API endpoints

- `GET  /api/autopilot/status` — `{enabled, running, last_runs, intervals, solve_batch}`
- `POST /api/autopilot/run-now` — trigger every phase once on a background thread
- `GET  /api/folder-watcher/status` — `{enabled, running, watching, exists, …}`
  (returns the **absolute path** so the user knows where to drop files)
- `POST /api/folder-watcher/scan-now` — force a folder rescan immediately

### Dashboard surfacing

- **Drop-folder banner** at the top: shows the absolute watched path
  (click to copy), running state, count of files picked up this process,
  and a "Run now" button that fires `scan-now` + `run-now` together.
- **Autopilot pill** in the header: `Autopilot · engaged / idle / off`
  with a live dot when the loop is currently inside a phase.
- The "Run Cycle" button is gone — the loop runs itself.

### Config (all in `.env.example`)

```
AUTOPILOT_ENABLED=true
AUTOPILOT_SOLVE_INTERVAL_SEC=45
AUTOPILOT_SOLVE_BATCH=3
AUTOPILOT_SEED_INTERVAL_SEC=60
AUTOPILOT_SYNTHESIS_INTERVAL_SEC=900
AUTOPILOT_HYPOTHESIS_INTERVAL_SEC=1800
AUTOPILOT_CONTRADICTIONS_INTERVAL_SEC=1200
AUTOPILOT_SCORE_INTERVAL_SEC=300

AUTO_INGEST_ENABLED=true
AUTO_INGEST_DIR=./data/dropbox
AUTO_INGEST_INTERVAL_SEC=10
AUTO_INGEST_STABLE_SEC=2.0
```

### Verified end-to-end

API restart → autopilot engaged within 1 s → solved a question and produced a
reflection within 11 s of boot, with **zero human input**. The drop folder
exists at `D:\Dream\apps\api\data\dropbox` and is reported as the absolute
path in the watcher status.

---

## Day 8 — Bulk folder ingest for 300+ PDFs

**Symptom:** ingesting a folder of 300 PDFs either hung, crashed with SQLite write
errors, or exhausted the NVIDIA free-tier rate limit (40 req/min) within seconds.

**Root cause:** `_enqueue_ingest()` spawned one bare `threading.Thread` per file,
resulting in 300 simultaneous ingest workers each making 5–10 LLM API calls.

### Fix: bounded in-process worker pool (`app/workers/inproc_queue.py`)

- **`queue.Queue(maxsize=2000)`** holds all pending ingest jobs.
- **N daemon worker threads** (default `INGEST_WORKERS=2`, max 8) pull one job
  at a time, call `ingest_pdf`, and update the `Job` row with
  `started_at / finished_at / status`.  Workers start lazily on first submission.
- **`_enqueue_ingest()`** now submits to the pool queue instead of spawning a
  raw thread. Celery still wins if available.
- **Batch DB insert**: the folder and batch endpoints write all `Job` rows in one
  SQLAlchemy transaction (was N separate transactions — O(N) lock contention on SQLite).
- **`GET /api/jobs/stats`** — returns `{queued_db, running, succeeded, failed,
  queue_depth, active_workers}`. Polled every 8 s by the dashboard.
- **Dashboard ingest-queue banner** — appears while jobs are waiting or active,
  showing waiting / active / done / failed counts. Disappears when idle.

**Tuning:** set `INGEST_WORKERS=2` for NVIDIA free tier (≈40 req/min shared
across workers).  Paid tiers can safely go to 4–6.

---

## Day 7 — Knowledge graph derived from SQL (no Neo4j needed)

**Symptom:** the Knowledge Graph page rendered an empty canvas — Neo4j is
disabled in zero-infra mode so `/api/graph` returned `{nodes:[], links:[]}`.

**Fix:** `app/db/neo4j_store.py::graph_snapshot()` now falls through to a new
`_graph_from_sql()` helper whenever Neo4j is unavailable or empty. It derives
the graph from data we already have in Postgres/SQLite:

| Node label | Source | Edge derived |
|---|---|---|
| **Paper** | `Document` | — |
| **Concept** | top 8 keywords per `Document.keywords` | `Paper -[MENTIONS]-> Concept` |
| **Insight** | `Insight` | `Insight -[SYNTHESIZES]-> Paper` (via `Insight.sources[].document_id`) |
| **Hypothesis** | `Hypothesis` | `Hypothesis -[FROM]-> Insight` (closest preceding insight in time) |
| **Contradiction** | `Contradiction` | `Contradiction -[INVOLVES]-> Paper` (resolved through `Chunk.document_id`) |

The graph route reports `source: "sql"` when this path is used so the UI can
distinguish SQL-derived from Neo4j-served (future enhancement).

### Frontend (`apps/web/app/graph/page.tsx`)
- Added Insight + Contradiction colors.
- Added node-size scaling by label (Papers larger than Concepts).
- Empty-state message: *"No nodes yet — upload a PDF and run a cycle."*
- Live legend + node/edge counters in the corner.

On the user's current corpus this produces 21 nodes / 63 edges out of the box.

---

## Day 6 — Manual Solve no longer ECONNRESETs

**Symptom:** clicking the **Solve** button on a question returned
`Error: API 500: Internal Server Error` even though the FastAPI handler
completed successfully (we saw `Solved q=… confidence=0.80` in the backend log).

**Root cause:** the Next.js dev-server proxy
(`Failed to proxy http://127.0.0.1:8000/api/questions/.../solve [Error: socket
hang up] { code: 'ECONNRESET' }`) was killing connections that took longer than
its default keep-alive window. The /solve endpoint ran the LLM call
**plus** the reflection LLM call inline, which on top of round-trip times
exceeded the proxy's tolerance and surfaced as a 500 to the browser even though
the backend was fine.

### Fixes
- **`POST /api/questions/{qid}/solve`** now returns the answer immediately and
  spawns reflection (which writes new memory + child questions) on a background
  thread. Down from ~20s+ to **~5s end-to-end**.
- **Frontend `lib/api.ts`** uses `NEXT_PUBLIC_API_URL` directly when set,
  bypassing the Next.js dev proxy entirely. CORS is already wide open on the
  backend so this is safe. Production builds still use the same-origin
  `/api/*` rewrite.
- **`components/folder-upload.tsx`** uses `apiUrl()` helper for batch + folder
  ingest endpoints (was hardcoded to `/api/...`).

---

## Day 4 / Day 5 — Runs anywhere + first end-to-end success

**Theme:** the user has no Docker. Get the whole loop working with zero infra,
fix a silent ingest hang, ship the first cycle that actually produces answers,
insights, and hypotheses.

### Day 4 — zero-infra mode
- **In-memory Qdrant** (`apps/api/app/db/qdrant.py`) — when `QDRANT_URL=memory://`
  or unreachable, swaps in a numpy-backed cosine store. Same call surface.
- **In-memory Redis** (`apps/api/app/db/redis_client.py`) — pubsub + ring buffer
  for the SSE feed work without Redis.
- **Lazy Neo4j** (`apps/api/app/db/neo4j_store.py`) — every op is a no-op when
  `NEO4J_URI` is empty. `neo4j` package no longer required.
- **`.env` resolves anywhere** — `config.py` searches cwd → api root → repo root.
- **`requirements.txt` slimmed** to NVIDIA-only zero-infra mode (no torch /
  qdrant-client / redis / neo4j / celery / psycopg). New `requirements-full.txt`
  contains the Docker-stack add-ons.
- `pymupdf` bumped to ≥ 1.25 for Python 3.13 wheel.
- `.env` defaults switched to `sqlite:///./data/evomind.db` + `memory://`.

### Day 5 — fix the silent ingest hang
**Root cause:** `deepseek-ai/deepseek-v4-pro` (the user's pasted example model)
times out after 60-90s on free-tier accounts. The OpenAI SDK's default
`max_retries` and missing `timeout` meant ingestion threads sat for minutes
without surfacing the error, and the upload-then-cycle race meant the cycle ran
on an empty corpus and reported `0 / 0 / 0`.

- **Default model changed** to `meta/llama-3.3-70b-instruct` (verified ~2s
  responses on free tier). DeepSeek / GLM still selectable via `NVIDIA_MODEL`.
- **Hard timeouts** on the NVIDIA OpenAI client (`nvidia_chat_timeout=60`,
  `nvidia_embed_timeout=30`) and `max_retries=0`. Bad model picks now fail
  in seconds with a visible `APITimeoutError` instead of hanging the worker.
- **Threaded ingest fallback** now sets `started_at`/`finished_at` and writes
  the truncated traceback into `Job.detail` on failure — `/api/jobs` now shows
  *exactly* why an ingest failed.
- **`NVIDIA_THINKING=false`** by default — thinking is opt-in per model.

### First successful cycle
On the user's PDF (1209.4290 — Cognitive Bias for Universal Algorithmic
Intelligence): 5s ingest, 39 chunks, 20 questions seeded, 4 solved at 0.75 avg
confidence, 7 follow-ups spawned, 3 insights synthesized, 3 hypotheses,
intelligence score **68.0**, ~33 LLM calls / 41k input + 4k output tokens.

---

## Day 3 — NVIDIA-only stack + folder ingestion

**Theme:** user wants NVIDIA Build to power everything (chat AND embeddings) and a
way to point the system at a folder of PDFs instead of uploading one at a time.

### Backend
- **`NvidiaEmbeddings`** in `apps/api/app/llm/providers/nvidia_p.py` — wraps
  `/v1/embeddings` with the OpenAI SDK. Default model `nvidia/nv-embedqa-e5-v5`
  (1024-dim). Passes `input_type: "query"` vs `"passage"` correctly via
  `extra_body` — meaningful retrieval-quality lift on retrieval-tuned models.
- **Embed call site plumbing**: `EmbeddingProvider.embed()` and the router's
  `embed()` accept a `kind` parameter. `hybrid_search` now uses `kind="query"`,
  `synthesize_topic` uses `kind="query"`, ingestion / dedupe / contradiction-scan
  remain `kind="passage"` (default).
- **Embedding usage tracking**: every `embed()` call records a `Usage` row with
  `purpose=embed:query` or `embed:passage` so embedding spend shows up in the
  dashboard widget alongside chat.
- **Auto-sized Qdrant collection**: `ensure_collection()` now reads the dim from
  the active embedding provider. If an existing collection's dim doesn't match,
  it raises a clear error pointing at the new admin endpoint.
- **`POST /api/admin/reset-vector-store`** — drop & recreate the Qdrant collection
  at the current provider's dim. Required when switching embedding providers.
- **Folder ingestion**:
  - `POST /api/upload/batch` — multipart with `files[]`, used by the browser
    folder picker (`webkitdirectory`). Skips non-PDFs silently.
  - `POST /api/upload/folder` — body `{path, recursive}` — server-side scan.
    Files are read directly from disk (no copy / no upload). Faster for local
    libraries with hundreds of PDFs.
  - Both reuse a shared `_enqueue_ingest()` helper (Celery → thread fallback).

### Frontend
- **`<FolderUpload />` modal** with two tabs:
  - **Browser folder picker** — multi-select via `webkitdirectory`, uploads PDFs.
  - **Server-side path** — type a path (e.g. `D:\Research\Papers` or
    `/app/data/library` inside Docker), tick "include subfolders", scan & ingest.
  - Shows a per-file queued list with the count and the scanned path.
- **Dashboard**: new "Ingest Folder" button next to "Upload PDF".

### Config
- `EMBEDDING_PROVIDER` default flipped to `nvidia`.
- `NVIDIA_EMBEDDING_MODEL=nvidia/nv-embedqa-e5-v5` added everywhere
  (`config.py`, `.env`, `.env.example`, `docker-compose.yml`).

### Why no more local embeddings by default
The user is on a free NVIDIA tier with no other API keys. Going NVIDIA-only
keeps everything coherent and avoids the ~80 MB sentence-transformers model
download on first ingest. Local is still selectable via `EMBEDDING_PROVIDER=local`.

---

## Day 2 — NVIDIA NIM as first-class provider

**Theme:** the user has free NVIDIA Build credits but no Anthropic/OpenAI key.
Adding NVIDIA NIM as a first-class provider so the autonomous loop runs end-to-end
on free infra.

### Backend
- **`apps/api/app/llm/providers/nvidia_p.py`** — new provider that targets the
  OpenAI-compatible NIM endpoint (`https://integrate.api.nvidia.com/v1`). Maps a
  generic `thinking` toggle onto each model family's vendor-specific
  `extra_body.chat_template_kwargs`:
  - DeepSeek v4 / R1 → `{thinking, reasoning_effort}`
  - Z-AI GLM → `{enable_thinking, clear_thinking}`
  - NVIDIA Nemotron → `{enable_thinking}` + `reasoning_budget`
  - Google Gemma → `{enable_thinking}`
  - Everything else (Llama, Mistral, …) → no extra body
  Discards `reasoning_content` (chain of thought) and returns only the final
  `content` so the JSON parser keeps working.
- **Router**: `app/llm/router.py` registers `nvidia` and resolves it before the
  other providers.
- **Config**: `app/core/config.py` adds `nvidia_api_key`, `nvidia_base_url`,
  `nvidia_model`, `nvidia_thinking`, `nvidia_reasoning_effort`. Default
  `PRIMARY_PROVIDER` flipped to `nvidia`.
- **Compose**: `docker-compose.yml` now passes the NVIDIA env into api/worker/beat.

### Config / docs
- `.env.example` documents the NVIDIA section + a curated catalog of models
  (DeepSeek v4 Pro, GLM 5.1, Nemotron 3 Super, Gemma 4, Llama 3.3).
- `.env` (gitignored) seeded for local dev with `nvidia` as primary.

### Why no `response_format={"type": "json_object"}` for NVIDIA
Not every NIM model accepts it; safer to rely on the prompt-level "return ONLY
JSON" instruction plus the tolerant parser in `complete_json`.

---

## Day 1 — Smarter retrieval + observability + wire dead modules

**Theme:** the loop runs end-to-end, but answers were retrieved via pure vector search
(misses literal keyword matches), token spend was invisible, and contradiction detection
was implemented but never called. Fixing all three.

### Backend

- **Hybrid retrieval** (`app/modules/retrieval/hybrid.py`): combines Qdrant vector search
  with an in-memory BM25 keyword index over the same chunks, fused with Reciprocal Rank
  Fusion (RRF). The solver now consistently returns evidence that matches both *meaning*
  and *exact terminology* (formulas, named entities, acronyms).
- **Contradiction detection wired into the cycle**: after each cycle, the orchestrator
  pairs the highest-confidence answers and runs LLM-based contradiction checks between
  their citation chunks. Any detected contradiction lands in the `contradictions` table
  and the live feed.
- **Token-usage tracking**: every LLM call now records `(provider, model, input_tokens,
  output_tokens, latency_ms, purpose)` to a new `usages` table. Exposed at
  `GET /api/usage/summary`.
- **Question dedupe**: the questioner embeds each candidate question and skips any whose
  cosine similarity to an existing question for the same document is ≥ 0.92. No more
  near-duplicate root questions on repeat ingests.
- **Document detail endpoints**: `GET /api/documents/{id}/chunks` (paginated),
  `GET /api/documents/{id}/questions`.

### Frontend

- **Document detail page** (`/documents/[id]`): metadata, keyword chips, paginated
  chunk viewer with section/page/kind tags, and the questions the system has asked
  about this document.
- **Dashboard usage widget**: today's tokens in/out per provider.
- **Dashboard documents table**: rows are now clickable → drill into the detail page.

### Reliability / housekeeping

- LLM JSON parser tolerates the model returning a top-level array instead of an object.
- Solver gracefully handles zero-evidence: returns confidence 0 and marks the question
  unresolved rather than hallucinating.
- `requirements.txt`: added `rank-bm25`.

---

## Day 0 — Initial scaffold

Full architecture (FastAPI + Next.js + Postgres + Qdrant + Neo4j + Redis + Celery),
ingestion → questioner → solver → learner → synthesis → score loop, dashboard /
feed / questions / graph / memory / reports / settings UI, Docker Compose.
