# Contributing to EvoMind PDF Intelligence

First off — **thank you!** 🎉 EvoMind is built to grow with its community, and every contribution
(code, docs, bug reports, ideas) genuinely helps.

This guide gets you from zero to your first pull request.

---

## Ways to contribute

- 🐛 **Report bugs** — open an issue using the Bug Report template.
- 💡 **Suggest features** — open an issue using the Feature Request template.
- 📝 **Improve docs** — even fixing a typo is a valid, welcome PR.
- 🔧 **Write code** — pick up a [good first issue](../../issues?q=label%3A%22good+first+issue%22) or
  propose your own.

If you're unsure whether an idea fits, open an issue first to discuss it — better to align early.

---

## Development setup

EvoMind is a monorepo: a FastAPI backend (`apps/api`) and a Next.js frontend (`apps/web`).

### Prerequisites
- **Python 3.11**
- **Node.js 20+**
- (Optional) **Docker** — easiest way to run the full data-store stack

### Fastest path — full stack with Docker

```bash
git clone <your-fork-url> evomind && cd evomind
cp .env.example .env          # add at least one LLM provider key
docker compose up --build
```

### Backend only (`apps/api`)

```bash
cd apps/api
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt                    # use requirements-full.txt for all stores
cp ../../.env.example .env
uvicorn app.main:app --reload --port 8000          # http://localhost:8000/docs
```

> 💡 No databases installed? The backend falls back to **SQLite**, in-memory Qdrant, and an
> in-process task queue, so you can develop without Docker or external services.

### Frontend only (`apps/web`)

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
npm run build      # must succeed (CI runs this; also type-checks the app)
```

---

## Where to start in the code

| You want to change… | Look in… |
|---------------------|----------|
| How questions are generated / the 9 categories | `apps/api/app/modules/questioner/` |
| Retrieval & grounded answering | `apps/api/app/modules/solver/` |
| Reflection / follow-up questions | `apps/api/app/modules/learner/` |
| Cross-doc insights, hypotheses, contradictions | `apps/api/app/modules/knowledge/` |
| The end-to-end research cycle | `apps/api/app/modules/orchestrator.py` |
| LLM providers & routing | `apps/api/app/llm/` |
| PDF parsing / chunking | `apps/api/app/ingestion/` |
| REST + SSE endpoints | `apps/api/app/api/routes.py` |
| UI pages | `apps/web/app/` |

### Testing your change locally

The quickest end-to-end smoke test: start the backend, drop a PDF into `data/dropbox/` (or POST to
`/upload`), then watch `/feed/stream` (or the Feed page) for question → solve → synthesize events.
`GET /health` and `GET /diagnostics` report runtime mode and dependency status.

---

## Patterns to respect

These are load-bearing — please don't bypass them without discussion:

- **LLM calls go through the provider router** (`apps/api/app/llm/router.py`). It handles JSON-mode
  normalization, retries (`tenacity`), and provider switching. Adding a provider? Implement
  `LLMProvider.complete(...)` in `apps/api/app/llm/providers/` and register it in the router.
- **Search goes through hybrid retrieval** (`apps/api/app/modules/retrieval/hybrid.py`) — it fuses
  Qdrant vectors and BM25 via Reciprocal Rank Fusion. Don't query a single store directly for search.
- **PDF parsing uses the fallback chain** (`apps/api/app/ingestion/parser.py`): LlamaParse → PyMuPDF
  → pdfplumber. If you touch parsing, keep all three paths working.
- **Adding a question category?** Update `VALID_CATEGORIES` in
  `apps/api/app/modules/questioner/engine.py`, the prompt in `apps/api/app/llm/prompts.py`, and the
  UI badge styles.
- **Never fabricate citations or skip confidence scoring** — answers without evidence are marked
  `unresolved`, not guessed.

---

## Pull request process

1. **Fork** the repo and create a branch from `master` (the default branch):
   - `feat/<short-name>` for features
   - `fix/<short-name>` for bug fixes
   - `docs/<short-name>` for documentation
2. Make focused commits with clear messages (present tense, e.g. `fix: dedupe near-duplicate questions`).
3. Before opening the PR, confirm:
   - [ ] `npm run build` succeeds (for frontend changes)
   - [ ] Backend imports cleanly (`python -m compileall app` from `apps/api`)
   - [ ] **No secrets committed** — never commit `.env`, API keys, or credentials
   - [ ] Docs updated if behavior changed
4. Open the PR using the template; link any related issue (e.g. `Closes #123`).
5. A maintainer will review. Be responsive to feedback — small iterations are normal and welcome.

---

## Backup & restore

The API can snapshot durable state on demand:

- `POST /api/backup/now` — create a backup (auth-gated). Writes to
  `<DATA_DIR>/backups/<id>/`.
- `GET /api/backup/status` / `GET /api/backup/list` — inspect backups.
- `GET /api/backup/{id}/download` — download a backup as a zip (auth-gated).

A daily backup also runs via Celery beat (`daily_backup_task`, 03:30 UTC).

**What's captured:** PostgreSQL (via `pg_dump`) or SQLite (online `.backup()`)
— the source of truth. Qdrant vectors and the Neo4j graph are *derivable* from
the relational data, so they're best-effort (Qdrant gets a server-side snapshot
when reachable) and noted in the manifest.

**Restoring:**
- SQLite: stop the API and replace the DB file with `database.sqlite` from the
  backup folder.
- Postgres: `psql "<dsn>" -f database.sql` into a clean database.
- Rebuild vectors/graph by letting the autopilot re-ingest/re-synthesise, or
  restore the Qdrant snapshot via the Qdrant API.

## Reporting security issues

Please do **not** open public issues for security vulnerabilities. Follow [SECURITY.md](SECURITY.md).

## Code of Conduct

By participating, you agree to uphold our [Code of Conduct](CODE_OF_CONDUCT.md). Be respectful and
constructive.

---

Happy hacking! If you get stuck, open a discussion or a draft PR — we'd rather help early than have
you blocked.
