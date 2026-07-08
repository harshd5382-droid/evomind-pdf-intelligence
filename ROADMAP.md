# EvoMind Roadmap

Where the project is, and where it's going. This is a living document — open an
[issue](https://github.com/harshd5382-droid/evomind-pdf-intelligence/issues) to propose a change.

Items marked **[good first issue]** are scoped for newcomers. Items marked **[help wanted]** need a
domain opinion, not just an implementation.

---

## Now — v0.2 "Trustworthy" (correctness & safety)

The research loop works. Before asking anyone to run it on real data, close the gaps that make it
unsafe to expose or lossy to operate.

| Item | Why |
|------|-----|
| Fail-closed auth (`AUTH_ENABLED=true` by default) | Compose publishes `:8000` on all interfaces with auth off. Every admin route is currently open. |
| Confine `POST /api/upload/folder` to an allow-listed root | Absolute paths pass the `..` guard, so any PDF readable by the API can be ingested and read back through `/chat`. |
| Protect the LLM-spending endpoints | `/run-autonomous-cycle`, `/analyze`, `/questions/{id}/solve`, `/autopilot/run-now` mutate and cost money with no auth, even when auth is on. |
| Register `SlowAPIMiddleware` | `RATE_LIMIT_DEFAULT` is currently never enforced — only `/upload` and `/chat` are limited. |
| Fix `DELETE /documents/{id}` | 500s on Postgres (FK violation from `questions`); silently orphans rows on SQLite. |
| Delete vectors + graph nodes on document delete | Deleted documents keep answering `/chat` queries from stale Qdrant payloads. |
| Un-block the SSE event loop | `/feed/stream` calls a blocking `pubsub.get_message()` inside an async generator; one open Feed tab stalls the whole API ~1s per poll. |
| Let rate-limit errors propagate from `complete_json` | It swallows every exception into `{}`, so the autopilot's 429 back-off never fires and outages look like "no evidence found". |
| Make `/healthz` treat *disabled* ≠ *degraded* | Returns 503 in the default zero-infra mode while the app is fully healthy. |
| Pick one scheduler | The in-process autopilot and Celery Beat both run in Docker and double-solve every question. |

## Next — v0.3 "Approachable" (developer experience)

| Item | Why |
|------|-----|
| **Screenshots + a demo GIF** **[good first issue]** ([#9](https://github.com/harshd5382-droid/evomind-pdf-intelligence/issues/9)) | This is a visual product with no visuals in the README. Highest-leverage change in the repo. |
| A `make demo` / `scripts/demo.sh` path | Ship a small public-domain PDF and a zero-key config (`EMBEDDING_PROVIDER=local` + Ollama) so a new user sees the loop run without signing up for anything. |
| Wire `CREATIVITY` to sampling temperature | Currently parsed, surfaced in the Settings UI, and read by nothing. Either wire it or remove the control. |
| Decide `AUTONOMY_LEVEL`'s meaning, or delete it | Same — a placebo knob in the UI. |
| `docs/TROUBLESHOOTING.md` | The top-3 failure modes (no API key, model timeout, dim mismatch after switching embedders) each need one paragraph. |
| Reconcile the three config sources | `config.py`, `.env.example`, and the README disagree on `RECURSION_DEPTH` and `AUTONOMY_LEVEL`. |
| Adopt Keep a Changelog + SemVer | `CHANGELOG.md` is a "Day N" development diary; it should be a release log. |

## Later — v0.4 "Scalable" (performance & architecture)

| Item | Why |
|------|-----|
| Replace per-query BM25 rebuild | `hybrid_search` re-reads and re-tokenizes the entire chunk table on every chat turn and every solve. Cache the index, or move to Postgres `tsvector` + GIN. |
| Stream `/api/export/training-corpus` | Materializes every answer, insight, and hypothesis into one JSON body. Should be JSONL with `Content-Disposition`. |
| Stop writing a `Metric` row per dashboard poll | `GET /api/metrics` is a cached *read* that calls `compute_score()`, which persists a snapshot. ~10k rows/day from an idle browser tab. |
| Unit-test the RRF fusion **[help wanted]** ([#4](https://github.com/harshd5382-droid/evomind-pdf-intelligence/issues/4)) | The core retrieval primitive has no direct test. |
| Alembic migrations | `alembic` is already a dependency but unused; schema changes ride on hand-rolled `ALTER TABLE`s in `_apply_simple_migrations()`. |
| Row-level claiming for the solve queue | Two workers can select and solve the same `open` question. |

## Someday — bigger bets

- **Reset / clear corpus endpoint + UI** ([#7](https://github.com/harshd5382-droid/evomind-pdf-intelligence/issues/7))
- **Hosted demo** — a read-only public instance with a pre-ingested corpus. The single biggest driver
  of stars for a project like this, and the hardest to do safely (see the auth work in v0.2).
- **Fine-tune loop closure** — the export + Colab notebook exist; nobody has run the round trip and
  reported back with numbers. A blog post doing so would be worth more than most features.
- **Multi-tenancy** — currently single-corpus, single-user by design.
- **Beyond PDFs** — EPUB, HTML, arXiv-by-ID ingestion.
- **Evaluation harness** — `modules/eval` scores faithfulness with an LLM judge. It needs a
  human-labelled gold set to calibrate against before the number means anything.

---

## Non-goals

Being explicit about what EvoMind is *not*, so contributors don't build the wrong thing:

- **Not a PDF chatbot.** Chat exists, but the point is the autonomous loop that runs when nobody is
  watching. Features that only improve one-shot Q&A are lower priority.
- **Not an enterprise RAG platform.** No multi-tenancy, no RBAC, no SSO on the roadmap.
- **Not a claim about machine consciousness.** The `identity`, `journal`, and `curiosity` modules
  implement cognitive *properties* that consciousness theories name as necessary. Whether that adds
  up to anything is a philosophical question the code does not answer, and the README should never
  imply it does.
