<div align="center">

![EvoMind PDF Intelligence](docs/banner.png)

# 🧠 EvoMind PDF Intelligence

### An autonomous research agent that reads your PDFs, asks its own questions, and grows a living knowledge graph.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![Next.js 15](https://img.shields.io/badge/Next.js-15-black.svg)](https://nextjs.org/)
[![React 19](https://img.shields.io/badge/React-19-61dafb.svg)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ed.svg)](https://www.docker.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![good first issues](https://img.shields.io/badge/good%20first%20issues-open-7057ff.svg)](../../issues?q=label%3A%22good+first+issue%22)

</div>

---

> **TL;DR** — Drop a PDF in. EvoMind parses it, generates its own research questions across 9
> categories, answers them with grounded evidence + citations, reflects on each answer to spawn
> deeper questions, synthesizes insights across your whole library, proposes testable hypotheses,
> hunts for contradictions, and tracks an evolving "intelligence score" — all on autopilot.

EvoMind is an open-source platform for turning a pile of PDFs into an active, self-expanding body
of knowledge. **This is not a PDF chatbot.** It runs a **continuous research loop** that keeps
learning while you sleep.

```
   ┌──────────┐   ┌──────────┐   ┌────────┐   ┌─────────┐   ┌────────────┐   ┌───────┐
   │  INGEST  │──▶│ QUESTION │──▶│ SOLVE  │──▶│ REFLECT │──▶│ SYNTHESIZE │──▶│ SCORE │──┐
   └──────────┘   └──────────┘   └────────┘   └─────────┘   └────────────┘   └───────┘  │
        ▲                                                                                │
        └────────────────────────────  repeat forever  ◀───────────────────────────────┘
```

---

## 📸 Demo

<!--
  To add screenshots: run the app, capture each page, and save the PNGs as
  docs/screenshots/dashboard.png, feed.png, and graph.png. They will render
  automatically below. Until then, the captions describe each view.
-->

### Dashboard — live metrics & intelligence score
<!-- ![Dashboard](docs/screenshots/dashboard.png) -->

### Research Feed — real-time SSE event stream
<!-- ![Research Feed](docs/screenshots/feed.png) -->

### Knowledge Graph — papers ↔ concepts ↔ hypotheses
<!-- ![Knowledge Graph](docs/screenshots/graph.png) -->

---

## ✨ Key Features

- **🤖 Autonomous research loop** — an in-process autopilot continuously seeds, solves, reflects,
  synthesizes, and scores. Your only job is to add PDFs.
- **❓ 9 question categories** — every document is interrogated from nine angles:
  `understanding`, `deep_logic`, `missing_data`, `contradiction`, `math`, `application`,
  `research`, `meta`, and `improvement`.
- **🔍 Grounded answers with citations** — hybrid retrieval fuses **Qdrant** dense-vector search
  with **BM25** lexical search via Reciprocal Rank Fusion, so answers cite real passages and report
  a confidence score. No evidence? The answer is marked _unresolved_ instead of hallucinated.
- **🧩 Recursive curiosity** — the learner reflects on each answer, extracts concepts, and spawns
  follow-up child questions up to a configurable recursion depth.
- **🌐 Cross-document synthesis** — unifies insights across your entire corpus, generates testable
  **hypotheses**, and detects **contradictions** between documents.
- **🧠 Persistent memory** — episodic / semantic / long-term memory lets the agent recall prior
  conclusions across the whole library, not just the current PDF.
- **📈 Evolving intelligence score** — a composite metric that rewards insights, hypotheses, and
  resolved questions, snapshotted over time for trend analysis.
- **📡 Real-time research feed** — a Server-Sent Events stream surfaces every cycle event live in
  the UI.
- **📥 Drop-folder auto-ingest** — point it at a folder; new PDFs are picked up, ingested, and
  reasoned over automatically (idempotent, dedup by content hash).
- **🔌 Multi-provider LLM routing** — NVIDIA NIM (default, free tier), Anthropic, OpenAI, Gemini,
  or local **Ollama** — switch with one env var. Embeddings via NVIDIA or fully offline
  sentence-transformers.

---

## 🏗️ Architecture

A TypeScript/React frontend talks to a FastAPI backend, which orchestrates four specialized data
stores and a pluggable LLM layer.

```
                       ┌──────────────────────────────┐
                       │      Next.js 15 / React 19    │
                       │  Dashboard · Feed · Questions  │
                       │  Graph · Memory · Reports      │
                       └──────────────┬───────────────┘
                                      │  REST + SSE
                       ┌──────────────▼───────────────┐
                       │        FastAPI (Python)       │
                       │ ingestion · questioner ·      │
                       │ solver · learner · synthesis  │
                       │ orchestrator · scorer · memory │
                       └──┬─────┬─────┬─────┬─────┬────┘
                          │     │     │     │     │
                    Postgres  Redis  Qdrant  Neo4j  Celery+Beat
                    (records) (queue (vector (graph) (workers,
                               +SSE)  store)         autopilot)
```

### Backend modules (`apps/api/app/modules/`)

| Module | Responsibility |
|--------|----------------|
| `orchestrator.py` | Drives one full research cycle end-to-end and publishes live events |
| `questioner/` | Generates the 9 categories of questions per document (dedupes near-duplicates) |
| `solver/` | Hybrid retrieval + grounded answering with confidence & citations |
| `learner/` | Reflection, concept extraction, and recursive follow-up questions |
| `knowledge/` | Cross-document insights, hypotheses, and contradiction detection |
| `intelligence/` | Composite intelligence score + history |
| `memory/` | Persistent episodic / semantic memory across the corpus |

### Data stores

| Store | Role |
|-------|------|
| **PostgreSQL** | Documents, chunks, questions, answers, insights, hypotheses, contradictions, jobs, metrics |
| **Qdrant** | Dense embeddings for semantic search (fused with BM25) |
| **Neo4j** | Knowledge graph — Paper / Concept / Insight / Hypothesis nodes |
| **Redis** | Celery broker/backend + SSE pub/sub |

> 💡 **Zero-infra dev mode:** the backend gracefully degrades to **SQLite**, in-memory Qdrant
> (`memory://`), and an in-process task queue — so you can hack on it with no Docker and no external
> databases. If Celery isn't running, uploads and cycles fall back to in-process execution.

---

## 🚀 Quickstart

### Option A — Full stack with Docker (recommended)

```bash
git clone <your-fork-url> evomind && cd evomind
cp .env.example .env          # then add your LLM API key (see Configuration)
docker compose up --build
```

| Service | URL |
|---------|-----|
| 🖥️ Web UI | http://localhost:3000 |
| 📚 API + Swagger docs | http://localhost:8000/docs |
| 🕸️ Neo4j Browser | http://localhost:7474 (`neo4j` / `evomind123`) |
| 📦 Qdrant Dashboard | http://localhost:6333/dashboard |

The Docker stack runs `api`, `web`, `worker` (Celery), `beat` (scheduler), plus `postgres`,
`redis`, `qdrant`, and `neo4j`.

### Option B — Run apps individually

**Frontend** (`apps/web`):
```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
```

**Backend** (`apps/api`):
```bash
cd apps/api
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt                    # minimal; requirements-full.txt for all stores
cp ../../.env.example .env
uvicorn app.main:app --reload --port 8000

# (optional) workers
celery -A app.workers.celery_app.celery worker --loglevel=info
celery -A app.workers.celery_app.celery beat   --loglevel=info
```

### Your first PDF

1. Get a **free** NVIDIA NIM API key at [build.nvidia.com](https://build.nvidia.com/settings/api-keys)
   and set `NVIDIA_API_KEY` in `.env`.
2. Either **upload** a PDF in the web UI, or **drop it** into `data/dropbox/` — the folder watcher
   ingests it automatically.
3. Open the **Feed** page and watch EvoMind generate questions, solve them, and synthesize insights
   in real time. The **Graph** page shows the knowledge graph filling in.

---

## ⚙️ Configuration

All configuration lives in `.env` (copy from [`.env.example`](.env.example)). The variables you'll
most likely touch:

| Variable | Default | What it does |
|----------|---------|--------------|
| `PRIMARY_PROVIDER` | `nvidia` | LLM provider: `nvidia` \| `anthropic` \| `openai` \| `gemini` \| `ollama` |
| `NVIDIA_API_KEY` | _(empty)_ | Required when using NVIDIA NIM (free at build.nvidia.com) |
| `EMBEDDING_PROVIDER` | `nvidia` | `nvidia` \| `local` (offline sentence-transformers) \| `openai` |
| `QUESTIONS_PER_DOC` | `10` | Root questions generated per document |
| `RECURSION_DEPTH` | `2` | How deep follow-up questions go |
| `AUTONOMY_LEVEL` | `balanced` | How aggressively the loop runs |
| `INGEST_WORKERS` | `2` | Parallel PDF ingest threads (keep at 2 for NVIDIA free tier) |
| `AUTOPILOT_ENABLED` | `true` | Run the continuous research loop automatically |

See [`.env.example`](.env.example) for the full annotated list (autopilot intervals, parser fallback
chain, infra DSNs, and more).

---

## 🗂️ Project Structure

```
evomind/
├── apps/
│   ├── api/                  # FastAPI backend (Python 3.11)
│   │   └── app/
│   │       ├── core/         # Settings + logging
│   │       ├── db/           # Postgres, Qdrant, Neo4j, Redis clients
│   │       ├── llm/          # Provider abstraction, router, prompts
│   │       ├── ingestion/    # PDF parse → chunk → embed pipeline
│   │       ├── modules/      # questioner, solver, learner, knowledge, intelligence, memory
│   │       ├── workers/      # Celery tasks + in-process fallback queue
│   │       └── api/          # REST routes + Pydantic schemas
│   └── web/                  # Next.js 15 / React 19 frontend
│       └── app/              # dashboard, feed, questions, graph, memory, reports, settings
├── docs/screenshots/         # README images (add yours here)
├── docker-compose.yml        # Full stack: api, web, worker, beat, postgres, redis, qdrant, neo4j
└── .env.example              # Annotated configuration template
```

---

## 🤝 Contributing

Contributions are very welcome — this project is built to grow with the community! 🎉

- Read **[CONTRIBUTING.md](CONTRIBUTING.md)** for dev setup, coding patterns, and the PR checklist.
- Browse **[good first issues](../../issues?q=label%3A%22good+first+issue%22)** to find an easy start.
- Be kind — we follow the **[Code of Conduct](CODE_OF_CONDUCT.md)**.
- Found a security issue? See **[SECURITY.md](SECURITY.md)** (please don't open a public issue).

**Great first contributions:** a new question category, an additional PDF parser, another LLM
provider, UI polish, tests, or docs. Adding a provider? Implement `LLMProvider.complete(...)` in
`apps/api/app/llm/providers/` and register it in `llm/router.py`.

---

## 📌 Project Status & Scope

EvoMind is a **strong, working foundation** — not a turnkey enterprise platform. Honest about what's
in the box:

**Works end-to-end today:** PDF upload → parse → chunk → embed → hybrid search · autonomous question
generation and grounded solving with confidence · depth-bounded self-learning loop · intelligence
score + history · live SSE feed · knowledge graph · autopilot + drop-folder ingest.

**Intentionally minimal (great contribution targets):** auth / multi-tenancy is stubbed (open API —
add JWT/OAuth as needed); the equation reasoner is sympy parsing + variable extraction; "teach me",
flashcards, and voice briefings are not yet implemented.

---

## 🧰 Tech Stack

**Frontend:** Next.js 15 · React 19 · TypeScript · Tailwind CSS · Recharts · react-force-graph-2d
**Backend:** FastAPI · SQLAlchemy 2 · Pydantic v2 · Celery · Loguru · tenacity
**AI/ML:** NVIDIA NIM · Anthropic · OpenAI · Gemini · Ollama · sentence-transformers · rank-bm25
**Data:** PostgreSQL · Qdrant · Neo4j · Redis
**Infra:** Docker · docker-compose

---

## 📄 License

Released under the [MIT License](LICENSE). Free to use, modify, and distribute — contributions back
are appreciated. ❤️

---

<div align="center">

**If EvoMind helps your research, please ⭐ the repo — it helps others find it!**

</div>
