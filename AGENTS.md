# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

**EvoMind PDF Intelligence** — an autonomous research-loop platform that ingests PDFs, generates questions, solves them with grounded evidence, reflects, and continuously expands a knowledge graph.

Core loop: ingest → question → solve → reflect → synthesize → score → repeat

## Commands

### Full Stack (recommended)
```bash
docker compose up --build
```

### Frontend only (apps/web)
```bash
cd apps/web
npm install
npm run dev        # port 3000
npm run build
npm run lint
```

### Backend only (apps/api)
```bash
cd apps/api
pip install -r requirements.txt   # minimal; use requirements-full.txt for all features
uvicorn app.main:app --reload --port 8000
```

### Workers (optional, or use Docker)
```bash
cd apps/api
celery -A app.workers.celery_app.celery worker --loglevel=info
celery -A app.workers.celery_app.celery beat --loglevel=info
```

### Service URLs (Docker)
- Web UI: http://localhost:3000
- API + Swagger: http://localhost:8000/docs
- Neo4j Browser: http://localhost:7474 (neo4j / evomind123)
- Qdrant Dashboard: http://localhost:6333/dashboard

## Architecture

### Monorepo Layout
```
apps/api/   FastAPI backend (Python 3.11)
apps/web/   Next.js 15 frontend (TypeScript/React 19)
infra/      Reserved (empty)
```

### Backend (`apps/api/app/`)

| Directory | Responsibility |
|-----------|----------------|
| `core/` | Pydantic settings (`config.py`, 60+ env vars) and Loguru logging |
| `db/` | PostgreSQL (SQLAlchemy 2), Qdrant (vectors), Redis (pubsub/cache), Neo4j (graph) |
| `llm/` | Provider abstraction, router, all prompts; providers: NVIDIA NIM, Anthropic, OpenAI, Gemini, Ollama, local sentence-transformers |
| `ingestion/` | PDF parse (LlamaParse → PyMuPDF → pdfplumber fallback chain), chunker, metadata extractor, pipeline |
| `modules/orchestrator.py` | Drives the research cycle end-to-end |
| `modules/questioner/` | Generates 9 question categories per document |
| `modules/solver/` | Hybrid retrieval (Qdrant vectors + BM25 RRF) + grounded answering |
| `modules/learner/` | Reflection, concept extraction, follow-up questions |
| `modules/knowledge/` | Cross-document synthesis, insights, hypotheses, contradictions |
| `modules/intelligence/` | Composite intelligence score + history |
| `workers/` | Celery tasks (ingest, cycle, daily at 04:00 UTC, snapshot) + in-process fallback queue |
| `api/routes.py` | 50+ FastAPI endpoints |
| `api/schemas.py` | All Pydantic request/response models |

### Frontend (`apps/web/`)

| Route | Purpose |
|-------|---------|
| `/dashboard` | Live metrics, recent activity, document list |
| `/feed` | Server-Sent Events stream of research events |
| `/questions` | Recursive question tree, manual solve |
| `/graph` | 2D force-graph (papers ↔ concepts ↔ hypotheses via react-force-graph-2d) |
| `/memory` | Memory vault and hypotheses |
| `/reports` | Insights and markdown export |
| `/documents/[id]` | Single document detail |
| `/settings` | Live server-side config UI |

`lib/api.ts` is the single HTTP client for all backend calls.

### Data Stores
- **PostgreSQL** — documents, chunks, questions, answers, insights, hypotheses, contradictions, jobs, usage
- **Qdrant** — embeddings for semantic search
- **Neo4j** — knowledge graph (Paper/Concept/Insight/Hypothesis nodes)
- **Redis** — Celery broker/backend + SSE pubsub

### LLM Provider Selection
Controlled by `PRIMARY_PROVIDER` and `EMBEDDING_PROVIDER` env vars. NVIDIA NIM is the default (uses the OpenAI-compatible SDK). Local embeddings (sentence-transformers/all-MiniLM-L6-v2, 384-dim) are available offline.

## Key Configuration

Copy `.env.example` to `.env`. Critical variables:

```
PRIMARY_PROVIDER=nvidia          # nvidia | anthropic | openai | gemini | ollama
NVIDIA_API_KEY=...               # free at build.nvidia.com
EMBEDDING_PROVIDER=nvidia        # or local (offline, no key needed)
QUESTIONS_PER_DOC=5
RECURSION_DEPTH=2
AUTONOMY_LEVEL=3                 # 1-5, controls how aggressively the loop runs
INGEST_WORKERS=2                 # max 8 for NVIDIA free tier rate limits
```

## Important Patterns

- **In-process fallback queue** (`workers/inproc_queue.py`): when Redis/Celery is unavailable, tasks run in a bounded thread pool. Routes detect this and degrade gracefully.
- **Provider router** (`llm/router.py`): always go through this for LLM calls — it handles JSON-mode normalization, retries via `tenacity`, and provider switching.
- **Hybrid retrieval** (`modules/retrieval/hybrid.py`): fuses Qdrant vector scores and BM25 lexical scores using Reciprocal Rank Fusion — don't bypass this for search.
- **PDF parse fallback chain**: `ingestion/parser.py` tries LlamaParse → PyMuPDF → pdfplumber in order; don't short-circuit this without updating all three parsers.
