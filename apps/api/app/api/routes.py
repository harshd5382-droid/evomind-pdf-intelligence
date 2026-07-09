from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from loguru import logger
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    AnalyzeRequest,
    AnswerOut,
    ChatMessageOut,
    ChatReply,
    ChatRequest,
    ConfigUpdate,
    ConversationOut,
    CycleRequest,
    DocumentOut,
    EvalRequest,
    FeedbackRequest,
    HypothesisOut,
    InsightOut,
    JobOut,
    MemoryOut,
    QuestionOut,
)
from app.core.cache import ttl_cache
from app.core.config import get_settings
from app.core.diagnostics import collect_runtime_diagnostics, integrity_report
from app.core.ratelimit import limiter
from app.core.security import require_api_key
from app.db import neo4j_store, postgres, qdrant, redis_client
from app.db.models import (
    Answer,
    ChatMessage,
    Chunk,
    Contradiction,
    Conversation,
    Document,
    Feedback,
    Hypothesis,
    Insight,
    Job,
    Memory,
    Question,
    Usage,
)
from app.modules.intelligence.scorer import compute_score, score_history
from app.modules.questioner.engine import generate_for_document

router = APIRouter()


def _empty_metrics_snapshot() -> dict:
    return {
        "score": 0.0,
        "documents": 0,
        "chunks": 0,
        "questions": 0,
        "answered": 0,
        "unresolved": 0,
        "insights": 0,
        "concepts": 0,
        "hypotheses": 0,
        "contradictions": 0,
        "avg_confidence": 0.0,
    }


def _db():
    yield from postgres.get_session()


def _event_time_ms(event: dict, fallback_ms: int | None = None) -> int:
    for key in ("_t", "timestamp_ms", "timestamp", "ts", "created_at"):
        value = event.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            n = int(value)
            return n if n > 10_000_000_000 else n * 1000
        if isinstance(value, str):
            try:
                n = int(float(value))
                return n if n > 10_000_000_000 else n * 1000
            except Exception:
                try:
                    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
                except Exception:
                    pass
    return fallback_ms if fallback_ms is not None else int(time.time() * 1000)


def _event_id(event: dict) -> str:
    for field in ("_event_id", "answer_id", "question_id", "document_id", "job_id", "id"):
        value = event.get(field)
        if value:
            prefix = event.get("type", "event")
            return f"{prefix}:{value}"
    digest = hashlib.sha1(json.dumps(event, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    return f"{event.get('type', 'event')}:{digest}"


def _normalize_event(event: dict, *, fallback_ms: int | None = None) -> dict:
    ev = dict(event or {})
    ev["_t"] = _event_time_ms(ev, fallback_ms=fallback_ms)
    ev["_event_id"] = _event_id(ev)
    return ev


# ------------- Health -------------
@router.get("/health")
def health():
    diag = collect_runtime_diagnostics()
    ok = bool(diag["dependencies"]["database"]["reachable"] and diag["providers"]["primary"]["configured"])
    return {
        "ok": ok,
        "runtime_mode": diag["runtime_mode"],
        "dependencies": diag["dependencies"],
        "providers": diag["providers"],
        "issues": diag["issues"],
    }

@router.get("/healthz")
def healthz():
    db = postgres.status()
    redis = redis_client.status()
    qdrant_store = qdrant.status()
    neo4j = neo4j_store.status()

    response = {
        "postgres": "ok" if db["reachable"] else "degraded",
        "redis": "ok" if redis["reachable"] else "degraded",
        "qdrant": "ok" if qdrant_store["reachable"] else "degraded",
        "neo4j": "ok" if neo4j["reachable"] else "degraded",
    }

    healthy = (
        db["reachable"]
        and redis["reachable"]
        and qdrant_store["reachable"]
        and neo4j["reachable"]
    )

    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if healthy
            else status.HTTP_503_SERVICE_UNAVAILABLE
    ),
    content=response,
)




@router.get("/diagnostics")
def diagnostics():
    return collect_runtime_diagnostics()


@router.get("/integrity")
def integrity():
    return integrity_report(repair=False)


@router.post("/integrity/repair", dependencies=[Depends(require_api_key)])
def integrity_repair():
    return integrity_report(repair=True)


@router.post("/admin/reset-vector-store", dependencies=[Depends(require_api_key)])
def reset_vector_store():
    """Drop & recreate the Qdrant collection at the current embedding provider's dim.

    Use after switching EMBEDDING_PROVIDER (the new dim won't match the old collection).
    Destructive: existing chunk vectors are gone — re-ingest documents to repopulate.
    """
    qdrant.reset_collection()
    return {"ok": True}


@router.get("/config")
def public_config():
    s = get_settings()
    return {
        "primary_provider": s.primary_provider,
        "embedding_provider": s.embedding_provider,
        "questions_per_doc": s.questions_per_doc,
        "recursion_depth": s.recursion_depth,
        "autonomy_level": s.autonomy_level,
        "creativity": s.creativity,
        "confidence_threshold": s.confidence_threshold,
        "autopilot_enabled": s.autopilot_enabled,
    }


@router.post("/config", dependencies=[Depends(require_api_key)])
def update_config(req: ConfigUpdate):
    """Apply runtime overrides for the tuning knobs. Takes effect immediately
    for the autopilot (it reads settings live) but is NOT persisted across a
    restart — set the corresponding env var in .env to make it permanent."""
    s = get_settings()
    changed = req.model_dump(exclude_none=True)
    for field, val in changed.items():
        setattr(s, field, val)
    if changed:
        logger.info("Runtime config updated: {}", changed)
    return {"ok": True, "changed": changed, "config": public_config()}


@router.get("/autopilot/status")
def autopilot_status():
    """Live status of the autonomous research loop."""
    from app.modules import autopilot
    return autopilot.status()


@router.post("/autopilot/run-now", dependencies=[Depends(require_api_key)])
def autopilot_run_now():
    """Trigger every autopilot phase immediately on a background thread,
    bypassing the interval gate. Useful for impatient debugging — the loop
    runs every phase by itself anyway."""
    import threading

    from app.modules import autopilot

    def _all_phases():
        try:
            autopilot._phase_seed_questions()
            autopilot._phase_solve_batch(max(1, get_settings().autopilot_solve_batch))
            autopilot._phase_synthesise()
            autopilot._phase_hypotheses()
            autopilot._phase_contradictions()
            autopilot._phase_score()
        except Exception as e:
            from loguru import logger
            logger.warning("autopilot run-now failed: {}", e)

    threading.Thread(target=_all_phases, name="autopilot-runnow", daemon=True).start()
    return {"queued": True}


@router.get("/folder-watcher/status")
def folder_watcher_status():
    """Live status of the auto-ingest folder watcher."""
    from app.modules import folder_watcher
    return folder_watcher.status()


@router.post("/folder-watcher/scan-now", dependencies=[Depends(require_api_key)])
def folder_watcher_scan_now():
    """Force an immediate scan of the auto-ingest folder."""
    from pathlib import Path

    from app.modules import folder_watcher
    s = get_settings()
    folder = Path(s.auto_ingest_dir).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    n = folder_watcher._scan_once(folder, s.auto_ingest_stable_sec)
    return {"enqueued": n, "watching": str(folder)}


# ------------- Identity (self-model) -------------
@router.get("/identity")
def get_identity():
    """The agent's current self-model: beliefs, open questions, active topics,
    confusion (recent contradictions), epistemic confidence, and a first-person
    narrative paragraph the agent maintains about itself."""
    from app.modules.identity import current_identity
    return current_identity()


@router.post("/identity/refresh", dependencies=[Depends(require_api_key)])
def refresh_identity():
    """Force an immediate identity recompile. Returns the new state."""
    import threading

    from app.modules.identity import update_identity
    # Run on a background thread — narrative LLM call can take a few seconds
    # and we don't want to block the request.
    def _run():
        try:
            update_identity()
        except Exception as e:
            logger.warning("identity refresh failed: {}", e)
    threading.Thread(target=_run, name="identity-refresh", daemon=True).start()
    return {"queued": True}


# ------------- Journal (Phase 3) -------------
@router.get("/journal")
def journal_recent(limit: int = Query(20, ge=1, le=100)):
    """The agent's recent first-person journal entries, newest first."""
    from app.modules.journal import recent_entries
    return {"items": recent_entries(limit=limit)}


@router.post("/journal/write-now", dependencies=[Depends(require_api_key)])
def journal_write_now():
    """Force the agent to write a journal entry immediately."""
    import threading

    from app.modules.journal import write_entry
    def _run():
        try:
            write_entry()
        except Exception as e:
            logger.warning("journal write-now failed: {}", e)
    threading.Thread(target=_run, name="journal-now", daemon=True).start()
    return {"queued": True}


# ------------- Curiosity (Phase 4) -------------
@router.get("/curiosity/gaps")
def curiosity_gaps_endpoint(
    limit: int = Query(12, ge=1, le=50),
    kind: str | None = Query(None, pattern="^(uncovered_concept|weak_hypothesis|low_confidence|open_contradiction)$"),
):
    """Current knowledge gaps the agent has identified about itself."""
    from app.modules.curiosity import current_gaps
    return {"items": current_gaps(limit=limit, kind=kind)}


@router.post("/curiosity/recompute", dependencies=[Depends(require_api_key)])
def curiosity_recompute():
    """Force-recompute the gap snapshot now."""
    import threading

    from app.modules.curiosity import compute_gaps, seed_gap_questions
    s = get_settings()
    def _run():
        try:
            compute_gaps()
            max_gaps = max(1, int(round(s.autopilot_solve_batch * s.autopilot_curiosity_question_ratio)))
            seed_gap_questions(max_gaps=max_gaps)
        except Exception as e:
            logger.warning("curiosity recompute failed: {}", e)
    threading.Thread(target=_run, name="curiosity-recompute", daemon=True).start()
    return {"queued": True}


# ------------- Training readiness (Phase 5) -------------
@router.get("/training/status")
def training_status():
    """Lightweight readiness check — counts only, no full export.

    Use this to render a "ready to fine-tune?" panel without paying the cost
    of materialising every training row. The full export is at
    /api/export/training-corpus."""
    s = get_settings()
    with postgres.session_scope() as sess:
        high_conf = sess.query(func.count(Answer.id)).filter(
            Answer.confidence >= 0.65
        ).scalar() or 0
        all_ans = sess.query(func.count(Answer.id)).scalar() or 0
        insights = sess.query(func.count(Insight.id)).scalar() or 0
        hypotheses = sess.query(func.count(Hypothesis.id)).scalar() or 0
    total = high_conf + insights + hypotheses

    if total < 200:
        stage, advice = "accumulating", (
            f"{total} training-quality examples. Need ~1,000 for a meaningful fine-tune. "
            "Drop more PDFs and let the autopilot run."
        )
    elif total < 1000:
        stage, advice = "early", (
            f"{total} examples — fine-tune will produce a weak shift in style. "
            "Better to wait until you have ≥ 1,000 for a real voice."
        )
    elif total < 10000:
        stage, advice = "ready", (
            f"{total} examples — solid territory. Open notebooks/evomind_qlora_finetune.ipynb "
            "in Colab/Kaggle and run end-to-end (≈45-60 min on a free T4)."
        )
    else:
        stage, advice = "mature", (
            f"{total} examples — large corpus. Consider full LoRA (not just QLoRA) and "
            "longer schedule. Worth a paid Colab session."
        )

    return {
        "stage": stage,
        "advice": advice,
        "ready": total >= 1000,
        "counts": {
            "high_confidence_answers": high_conf,
            "total_answers": all_ans,
            "insights": insights,
            "hypotheses": hypotheses,
            "total_training_examples": total,
        },
        "active_provider": s.primary_provider,
        "ollama_model": s.ollama_model,
        "notebook_path": "notebooks/evomind_qlora_finetune.ipynb",
        "export_endpoint": "/api/export/training-corpus",
    }


# ------------- Training corpus export -------------
@router.get("/export/training-corpus")
def export_training_corpus(
    min_confidence: float = Query(0.65, ge=0.0, le=1.0),
    include_insights: bool = Query(True),
    include_hypotheses: bool = Query(True),
    format: str = Query("alpaca", pattern="^(alpaca|sharegpt|raw)$"),
):
    """Export the agent's accumulated knowledge as a fine-tuning dataset.

    Designed to feed directly into a Colab/Kaggle QLoRA notebook for Phase 5.
    Three formats:
      - alpaca:    {instruction, input, output}            (most fine-tuners)
      - sharegpt:  {conversations: [{from, value}, ...]}    (newer chat format)
      - raw:       {question, answer, reasoning, source}    (unopinionated)

    Only answers at or above `min_confidence` are included — we never want
    the agent to learn from its own low-confidence guesses, that compounds
    error.
    """
    rows: list[dict] = []
    stats = {"answers": 0, "insights": 0, "hypotheses": 0}

    with postgres.session_scope() as s:
        # 1. High-confidence Q→A pairs — the spine of the training set.
        ans_rows = (
            s.query(Question, Answer)
            .join(Answer, Answer.question_id == Question.id)
            .filter(Answer.confidence >= min_confidence)
            .all()
        )
        for q, a in ans_rows:
            instruction = q.text
            output = a.text
            reasoning = a.reasoning or ""
            citations = a.citations or []
            evidence_lines = [
                f"[{i}] {c.get('snippet','')[:280]}"
                for i, c in enumerate(citations[:4])
            ]
            evidence = "\n".join(evidence_lines)

            if format == "alpaca":
                rows.append({
                    "instruction": instruction,
                    "input": evidence,
                    "output": (
                        f"{output}\n\nReasoning: {reasoning}" if reasoning else output
                    ),
                    "source": "qa",
                    "confidence": a.confidence,
                })
            elif format == "sharegpt":
                rows.append({
                    "conversations": [
                        {"from": "system", "value":
                            "You are a careful research assistant grounded in the provided evidence. "
                            "Cite by [#] indices when relevant."},
                        {"from": "human", "value":
                            (f"{instruction}\n\nEvidence:\n{evidence}" if evidence else instruction)},
                        {"from": "gpt", "value":
                            (f"{output}\n\nReasoning: {reasoning}" if reasoning else output)},
                    ],
                    "source": "qa",
                    "confidence": a.confidence,
                })
            else:  # raw
                rows.append({
                    "question": instruction, "answer": output,
                    "reasoning": reasoning, "evidence": evidence,
                    "source": "qa", "confidence": a.confidence,
                })
            stats["answers"] += 1

        # 2. Insights — teach synthesis behaviour.
        if include_insights:
            for ins in s.query(Insight).order_by(Insight.created_at.desc()).all():
                instruction = f"Synthesize what the literature says about: {ins.title}"
                output = ins.body or ""
                if not output.strip():
                    continue
                if format == "alpaca":
                    rows.append({"instruction": instruction, "input": "",
                                 "output": output, "source": "insight"})
                elif format == "sharegpt":
                    rows.append({"conversations": [
                        {"from": "human", "value": instruction},
                        {"from": "gpt",   "value": output},
                    ], "source": "insight"})
                else:
                    rows.append({"question": instruction, "answer": output,
                                 "source": "insight"})
                stats["insights"] += 1

        # 3. Hypotheses — teach speculative-but-grounded reasoning.
        if include_hypotheses:
            for h in s.query(Hypothesis).order_by(Hypothesis.created_at.desc()).all():
                if not h.statement:
                    continue
                instruction = "Propose a testable hypothesis grounded in recent observations."
                output = (
                    f"Hypothesis: {h.statement}\n\n"
                    f"Rationale: {h.rationale or '(none)'}\n"
                    f"Testable: {bool(h.testable)}"
                )
                if format == "alpaca":
                    rows.append({"instruction": instruction, "input": "",
                                 "output": output, "source": "hypothesis"})
                elif format == "sharegpt":
                    rows.append({"conversations": [
                        {"from": "human", "value": instruction},
                        {"from": "gpt",   "value": output},
                    ], "source": "hypothesis"})
                else:
                    rows.append({"question": instruction, "answer": output,
                                 "source": "hypothesis"})
                stats["hypotheses"] += 1

    return {
        "format": format,
        "min_confidence": min_confidence,
        "count": len(rows),
        "stats": stats,
        "ready_to_train": len(rows) >= 200,
        "recommendation": _training_threshold_message(len(rows)),
        "rows": rows,
    }


def _training_threshold_message(n: int) -> str:
    if n < 200:
        return (f"{n} examples — too few to fine-tune meaningfully. "
                "Aim for ≥ 1,000. Drop more PDFs and let the autopilot run.")
    if n < 1000:
        return (f"{n} examples — fine-tune will produce a weak shift in behaviour. "
                "Better to wait until you have ≥ 1,000 for a real 'voice'.")
    if n < 10000:
        return (f"{n} examples — solid fine-tune territory. QLoRA on Llama-3-8B "
                "in Colab/Kaggle will give the agent a recognisable house style.")
    return (f"{n} examples — large corpus. Consider a full LoRA (not just QLoRA) "
            "and a longer schedule. Worth a paid Colab session.")


# ------------- Memory -------------
@router.get("/memory/stats")
def memory_stats_endpoint():
    """Total memories, how many are embedded, and a per-source breakdown."""
    from app.modules.memory import memory_stats
    return memory_stats()


@router.get("/memory/search")
def memory_search_endpoint(q: str = Query(...), k: int = Query(8, ge=1, le=50)):
    """Semantic search across the agent's memory bank — every insight,
    hypothesis, contradiction, reflection, or high-confidence answer it has
    ever formed. Returns the top-K most relevant memories with scores."""
    from app.modules.memory import search_memories
    hits = search_memories(q, k=k, min_score=0.20)
    return {
        "query": q,
        "count": len(hits),
        "items": [{
            "id": h.id,
            "content": h.content,
            "layer": h.layer,
            "importance": h.importance,
            "source_kind": h.source_kind,
            "source_id": h.source_id,
            "score": round(h.score, 4),
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in hits],
    }


# ------------- Upload + ingest -------------
def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 of a file's bytes, streamed (constant memory)."""
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_duplicate(content_hash: str) -> Document | None:
    """Return an existing Document with this content_hash, if any."""
    if not content_hash:
        return None
    with postgres.session_scope() as s:
        row = s.execute(
            select(Document).where(Document.content_hash == content_hash).limit(1)
        ).scalar_one_or_none()
        if row is not None:
            # Detach so the caller can read attributes after the session closes.
            s.expunge(row)
        return row


def _enqueue_ingest(file_path: str, doc_id: str, job_id: str) -> bool:
    """Try Celery first; fall back to the in-process worker-pool queue."""
    try:
        from app.workers.tasks import ingest_task
        ingest_task.delay(file_path, document_id=doc_id, job_id=job_id)
        return True
    except Exception:
        pass

    # Celery unavailable — submit to the bounded in-process queue.
    # The pool (default 2 workers) processes one PDF at a time per worker,
    # preventing SQLite write storms and NVIDIA rate-limit exhaustion.
    import queue as _queue_mod

    from app.workers.inproc_queue import submit_ingest
    try:
        submit_ingest(file_path, doc_id, job_id)
    except _queue_mod.Full:
        from loguru import logger
        logger.warning("Ingest queue full — dropping job {} for {}", job_id, file_path)
    return False


def _validate_pdf_filename(file: UploadFile) -> None:
    """Reject anything that isn't a PDF by extension or declared content type."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are accepted")
    ctype = (file.content_type or "").lower()
    if ctype and ctype not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(400, f"Unexpected content type for a PDF: {ctype}")


async def _save_upload(file: UploadFile, target: Path, max_bytes: int) -> None:
    """Stream an upload to disk, enforcing a size cap and a %PDF magic check.

    Aborts and removes the partial file if the cap is exceeded or the content
    isn't actually a PDF (defends against a non-PDF renamed to .pdf)."""
    written = 0
    first = b""
    with target.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            if not first:
                first = chunk[:5]
            written += len(chunk)
            if written > max_bytes:
                f.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
            f.write(chunk)
    if not first.startswith(b"%PDF"):
        target.unlink(missing_ok=True)
        raise HTTPException(400, "File does not look like a valid PDF (missing %PDF header)")


@router.post("/upload", dependencies=[Depends(require_api_key)])
@limiter.limit(get_settings().rate_limit_upload)
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    s = get_settings()
    Path(s.upload_dir).mkdir(parents=True, exist_ok=True)
    _validate_pdf_filename(file)
    filename = file.filename or ""  # guaranteed non-empty by the validation above

    doc_id = str(uuid.uuid4())
    safe_name = f"{doc_id}_{Path(filename).name}"
    target = Path(s.upload_dir) / safe_name
    await _save_upload(file, target, s.max_upload_mb * 1024 * 1024)

    # Dedup: hash the file we just wrote and look for an existing document
    # with identical content. If found, delete the duplicate copy from disk
    # and return the existing record — no LLM calls wasted, no row added.
    try:
        content_hash = _hash_file(target)
    except Exception as e:
        logger.warning("Hash failed for {}: {}", target, e)
        content_hash = ""

    existing = _find_duplicate(content_hash)
    if existing is not None:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        logger.info("Skipped duplicate upload (matches doc {}): {}", existing.id, file.filename)
        return {
            "document_id": existing.id,
            "job_id": None,
            "queued": False,
            "duplicate": True,
            "original_filename": existing.filename,
            "message": f"This PDF is already in your library as '{existing.filename}'.",
        }

    job_id = str(uuid.uuid4())
    with postgres.session_scope() as session:
        session.add(Job(id=job_id, kind="ingest", target_id=doc_id, status="queued", detail=safe_name))
        # Pre-register the document with its hash so concurrent uploads of the
        # same file don't slip past the dedup check before ingest finishes.
        session.add(Document(
            id=doc_id, title=Path(filename).stem, filename=filename,
            path=str(target), content_hash=content_hash, status="pending",
        ))

    queued = _enqueue_ingest(str(target), doc_id, job_id)
    return {"document_id": doc_id, "job_id": job_id, "queued": queued, "duplicate": False}


@router.post("/upload/batch", dependencies=[Depends(require_api_key)])
async def upload_pdf_batch(files: list[UploadFile] = File(...)):
    """Multi-file upload — used by the browser folder picker (webkitdirectory).

    Skips files that are not .pdf and returns one row per accepted file.
    Files whose SHA-256 already exists in the library are reported as
    duplicates and not re-ingested (no LLM calls wasted).
    """
    s = get_settings()
    Path(s.upload_dir).mkdir(parents=True, exist_ok=True)

    # Write files to disk + hash them. Track new vs duplicate.
    new_items: list[tuple[str, str, str, str, str]] = []  # (doc_id, job_id, target, fname, hash)
    dup_items: list[dict] = []
    rejected_items: list[dict] = []  # files that failed validation (bad type / oversized)
    intra_batch_hashes: dict[str, str] = {}  # hash → doc_id (catch dupes within this same batch)
    max_bytes = s.max_upload_mb * 1024 * 1024

    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            continue
        doc_id = str(uuid.uuid4())
        safe_name = f"{doc_id}_{Path(file.filename).name}"
        target = Path(s.upload_dir) / safe_name
        # Reuse the single-upload guard: enforces the per-file size cap and the
        # %PDF magic check, aborting+removing the partial file on violation. A
        # rejected file is reported rather than failing the whole batch.
        try:
            await _save_upload(file, target, max_bytes)
        except HTTPException as e:
            rejected_items.append({
                "filename": file.filename,
                "rejected": True,
                "reason": e.detail,
            })
            continue

        try:
            content_hash = _hash_file(target)
        except Exception as e:
            logger.warning("Hash failed for {}: {}", target, e)
            content_hash = ""

        # Check the existing library
        existing = _find_duplicate(content_hash) if content_hash else None
        # Also catch duplicates within this same batch
        intra_dup_id = intra_batch_hashes.get(content_hash) if content_hash else None

        if existing is not None or intra_dup_id is not None:
            try: target.unlink(missing_ok=True)
            except Exception: pass
            dup_items.append({
                "document_id": existing.id if existing else intra_dup_id,
                "filename": file.filename,
                "duplicate": True,
                "original_filename": existing.filename if existing else file.filename,
            })
            continue

        job_id = str(uuid.uuid4())
        new_items.append((doc_id, job_id, str(target), file.filename, content_hash))
        if content_hash:
            intra_batch_hashes[content_hash] = doc_id

    # Single DB transaction: Job rows + pre-registered Document shells with hash
    with postgres.session_scope() as session:
        for doc_id, job_id, target_path, fname, chash in new_items:
            session.add(Job(id=job_id, kind="ingest", target_id=doc_id,
                            status="queued", detail=Path(fname).name))
            session.add(Document(
                id=doc_id, title=Path(fname).stem, filename=fname,
                path=target_path, content_hash=chash, status="pending",
            ))

    # Enqueue all new files (returns immediately — bounded in-process queue)
    out: list[dict] = []
    for doc_id, job_id, target_path, fname, _ in new_items:
        _enqueue_ingest(target_path, doc_id, job_id)
        out.append({"document_id": doc_id, "job_id": job_id, "filename": fname,
                    "queued": False, "duplicate": False})
    out.extend(dup_items)
    out.extend(rejected_items)
    return {
        "count": len(out),
        "new": len(new_items),
        "duplicates": len(dup_items),
        "rejected": len(rejected_items),
        "items": out,
    }


@router.post("/upload/folder", dependencies=[Depends(require_api_key)])
def ingest_folder(payload: dict):
    """Ingest every PDF found under a server-side folder path.

    Faster than uploading because the API process reads files directly from disk.
    Use this when the API is running on the same host as your PDF library.
    """
    raw_path = (payload or {}).get("path", "").strip()
    recursive = bool((payload or {}).get("recursive", True))
    if not raw_path:
        raise HTTPException(400, "Missing 'path'")
    # Reject path-traversal segments before resolving, so a caller can't walk
    # up out of an intended directory via "..".
    if ".." in Path(raw_path).parts:
        raise HTTPException(400, "Path traversal ('..') is not allowed")

    # Resolve to an absolute, symlink-collapsed path and confine it to the
    # configured ingest root. Without this, an absolute path (no ".." needed)
    # like "/etc" or "C:\\Users" would let a caller enumerate/ingest any PDF on
    # the host — a file-disclosure vector even though this route requires auth.
    folder = Path(raw_path).expanduser().resolve()
    root = get_settings().folder_ingest_root_path
    if not folder.is_relative_to(root):
        raise HTTPException(403, f"Path must be inside the ingest root: {root}")
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(400, f"Folder not found or not a directory: {folder}")

    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdfs = sorted(folder.glob(pattern))
    if not pdfs:
        return {"count": 0, "items": [], "scanned": str(folder)}

    # Hash every file first; split into new vs duplicate.
    new_items: list[tuple[str, str, Path, str]] = []  # (doc_id, job_id, pdf_path, hash)
    dup_items: list[dict] = []
    intra_batch_hashes: dict[str, str] = {}

    for pdf in pdfs:
        try:
            content_hash = _hash_file(pdf)
        except Exception as e:
            logger.warning("Hash failed for {}: {}", pdf, e)
            content_hash = ""

        existing = _find_duplicate(content_hash) if content_hash else None
        intra_dup_id = intra_batch_hashes.get(content_hash) if content_hash else None
        if existing is not None or intra_dup_id is not None:
            dup_items.append({
                "document_id": existing.id if existing else intra_dup_id,
                "filename": pdf.name,
                "duplicate": True,
                "original_filename": existing.filename if existing else pdf.name,
            })
            continue

        doc_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        new_items.append((doc_id, job_id, pdf, content_hash))
        if content_hash:
            intra_batch_hashes[content_hash] = doc_id

    # Single DB transaction: Job rows + pre-registered Document shells with hash
    with postgres.session_scope() as session:
        for doc_id, job_id, pdf, chash in new_items:
            session.add(Job(id=job_id, kind="ingest", target_id=doc_id,
                            status="queued", detail=pdf.name))
            session.add(Document(
                id=doc_id, title=pdf.stem, filename=pdf.name,
                path=str(pdf), content_hash=chash, status="pending",
            ))

    out: list[dict] = []
    for doc_id, job_id, pdf, _ in new_items:
        _enqueue_ingest(str(pdf), doc_id, job_id)
        out.append({"document_id": doc_id, "job_id": job_id, "filename": pdf.name,
                    "queued": False, "duplicate": False})
    out.extend(dup_items)
    return {
        "count": len(out),
        "new": len(new_items),
        "duplicates": len(dup_items),
        "items": out,
        "scanned": str(folder),
    }


# ------------- Analyze (generate questions for one doc) -------------
@router.post("/analyze", dependencies=[Depends(require_api_key)])
def analyze(req: AnalyzeRequest):
    try:
        ids = generate_for_document(req.document_id, n=req.n_questions)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"question_ids": ids, "count": len(ids)}


# ------------- Autonomous cycle -------------
@router.post("/run-autonomous-cycle", dependencies=[Depends(require_api_key)])
def run_cycle_endpoint(req: CycleRequest):
    job_id = str(uuid.uuid4())
    with postgres.session_scope() as s:
        s.add(Job(id=job_id, kind="cycle", status="queued", detail=f"budget={req.question_budget}"))
    try:
        from app.workers.tasks import cycle_task
        cycle_task.delay(question_budget=req.question_budget, job_id=job_id)
        return {"job_id": job_id, "queued": True}
    except Exception:
        # Run synchronously if no worker available
        from app.modules.orchestrator import run_cycle
        with postgres.session_scope() as s:
            j = s.get(Job, job_id)
            if j:
                j.status = "running"
        try:
            summary = run_cycle(question_budget=req.question_budget)
            with postgres.session_scope() as s:
                j = s.get(Job, job_id)
                if j:
                    j.status = "succeeded"; j.progress = 1.0
            return {"job_id": job_id, "queued": False, "summary": summary}
        except Exception as e:
            with postgres.session_scope() as s:
                j = s.get(Job, job_id)
                if j:
                    j.status = "failed"; j.detail = str(e)
            raise HTTPException(500, str(e))


# ------------- Documents / chunks -------------
@router.get("/documents", response_model=list[DocumentOut])
def list_documents(s: Session = Depends(_db)):
    try:
        return s.execute(select(Document).order_by(desc(Document.created_at))).scalars().all()
    except Exception as e:
        logger.warning("Documents unavailable: {}", e)
        return []


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str, s: Session = Depends(_db)):
    d = s.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "document not found")
    return d


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_api_key)])
def delete_document(doc_id: str, s: Session = Depends(_db)):
    d = s.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "document not found")
    s.delete(d)
    s.commit()
    return {"ok": True}


@router.get("/documents/{doc_id}/chunks")
def document_chunks(
    doc_id: str,
    offset: int = 0,
    limit: int = Query(50, le=200),
    kind: str | None = None,
    s: Session = Depends(_db),
):
    if not s.get(Document, doc_id):
        raise HTTPException(404, "document not found")
    q = select(Chunk).where(Chunk.document_id == doc_id)
    if kind:
        q = q.where(Chunk.kind == kind)
    total = s.query(func.count(Chunk.id)).filter(Chunk.document_id == doc_id).scalar() or 0
    rows = s.execute(q.order_by(asc(Chunk.ord)).offset(offset).limit(limit)).scalars().all()
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "chunks": [
            {
                "id": c.id, "ord": c.ord, "page": c.page, "section": c.section,
                "kind": c.kind, "text": c.text,
            }
            for c in rows
        ],
    }


@router.get("/documents/{doc_id}/questions", response_model=list[QuestionOut])
def document_questions(doc_id: str, s: Session = Depends(_db)):
    if not s.get(Document, doc_id):
        raise HTTPException(404, "document not found")
    return s.execute(
        select(Question).where(Question.document_id == doc_id)
        .order_by(desc(Question.priority), asc(Question.created_at))
    ).scalars().all()


# ------------- Questions -------------
@router.get("/questions", response_model=list[QuestionOut])
def list_questions(
    status: str | None = None,
    document_id: str | None = None,
    parent_id: str | None = None,
    limit: int = Query(100, le=500),
    s: Session = Depends(_db),
):
    q = select(Question)
    if status:
        q = q.where(Question.status == status)
    if document_id:
        q = q.where(Question.document_id == document_id)
    if parent_id == "null":
        q = q.where(Question.parent_id.is_(None))
    elif parent_id:
        q = q.where(Question.parent_id == parent_id)
    q = q.order_by(desc(Question.priority), asc(Question.created_at)).limit(limit)
    return s.execute(q).scalars().all()


@router.get("/questions/{qid}/answers", response_model=list[AnswerOut])
def question_answers(qid: str, s: Session = Depends(_db)):
    return s.execute(select(Answer).where(Answer.question_id == qid).order_by(desc(Answer.created_at))).scalars().all()


@router.get("/questions/{qid}/tree")
def question_tree(qid: str, s: Session = Depends(_db)):
    """Tree from a root question. Loads level-by-level (one query per depth via
    parent_id IN (...)) instead of one query per node, avoiding the N+1 the
    naive recursion caused."""
    root = s.get(Question, qid)
    if not root:
        raise HTTPException(404, "question not found")

    def node(q: Question) -> dict:
        return {
            "id": q.id, "text": q.text, "category": q.category,
            "status": q.status, "priority": q.priority, "depth": q.depth,
            "children": [],
        }

    nodes = {root.id: node(root)}
    frontier = [root.id]
    seen = {root.id}
    while frontier:
        children = s.execute(
            select(Question).where(Question.parent_id.in_(frontier))
        ).scalars().all()
        next_frontier: list[str] = []
        for c in children:
            if c.id in seen:  # guard against cycles
                continue
            seen.add(c.id)
            cd = node(c)
            nodes[c.id] = cd
            parent = nodes.get(c.parent_id) if c.parent_id else None
            if parent is not None:
                parent["children"].append(cd)
            next_frontier.append(c.id)
        frontier = next_frontier
    return nodes[root.id]


@router.post("/questions/{qid}/solve", dependencies=[Depends(require_api_key)])
def manually_solve(qid: str):
    """Solve a question and return the answer immediately. Reflection (which spawns
    follow-up questions and writes memory) runs in a background thread so the
    HTTP response returns fast and the UI doesn't stall the proxy."""
    import threading

    from loguru import logger

    from app.modules.learner.engine import reflect_and_expand
    from app.modules.solver.engine import solve_question

    res = solve_question(qid)

    def _reflect_bg():
        try:
            reflect_and_expand(qid, res["answer"], res["confidence"])
        except Exception as e:
            logger.warning("Background reflection failed for q={}: {}", qid, e)

    threading.Thread(target=_reflect_bg, daemon=True).start()
    return res


# ------------- Insights / memory / hypotheses / contradictions -------------
@router.get("/insights", response_model=list[InsightOut])
def list_insights(limit: int = 100, s: Session = Depends(_db)):
    try:
        return s.execute(select(Insight).order_by(desc(Insight.created_at)).limit(limit)).scalars().all()
    except Exception as e:
        logger.warning("Insights unavailable: {}", e)
        return []


@router.get("/memory", response_model=list[MemoryOut])
def list_memory(layer: str | None = None, limit: int = 200, s: Session = Depends(_db)):
    try:
        q = select(Memory)
        if layer:
            q = q.where(Memory.layer == layer)
        q = q.order_by(desc(Memory.created_at)).limit(limit)
        return s.execute(q).scalars().all()
    except Exception as e:
        logger.warning("Memory unavailable: {}", e)
        return []


@router.get("/hypotheses", response_model=list[HypothesisOut])
def list_hypotheses(limit: int = 100, s: Session = Depends(_db)):
    try:
        return s.execute(select(Hypothesis).order_by(desc(Hypothesis.created_at)).limit(limit)).scalars().all()
    except Exception as e:
        logger.warning("Hypotheses unavailable: {}", e)
        return []


@router.get("/contradictions")
def list_contradictions(limit: int = 100, s: Session = Depends(_db)):
    try:
        rows = s.execute(select(Contradiction).order_by(desc(Contradiction.created_at)).limit(limit)).scalars().all()
        return [
            {
                "id": r.id, "summary": r.summary, "severity": r.severity,
                "a_chunk_id": r.a_chunk_id, "b_chunk_id": r.b_chunk_id,
                "created_at": r.created_at.isoformat(),
            } for r in rows
        ]
    except Exception as e:
        logger.warning("Contradictions unavailable: {}", e)
        return []


# ------------- Graph -------------
@router.get("/graph")
def graph_snapshot(limit: int = 200):
    try:
        snapshot = neo4j_store.graph_snapshot(limit=limit)
        snapshot.setdefault("source", "neo4j")
        snapshot["degraded"] = bool(snapshot.get("source") != "neo4j")
        return snapshot
    except Exception as e:
        return {"nodes": [], "links": [], "source": "unavailable", "degraded": True, "error": str(e)}


# ------------- Reports -------------
@router.get("/reports")
def list_reports(s: Session = Depends(_db)):
    rows = s.execute(select(Insight).order_by(desc(Insight.created_at)).limit(50)).scalars().all()
    return [{"id": r.id, "title": r.title, "kind": r.kind, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/reports/{insight_id}/markdown")
def report_markdown(insight_id: str, s: Session = Depends(_db)):
    ins = s.get(Insight, insight_id)
    if not ins:
        raise HTTPException(404, "insight not found")
    md = f"# {ins.title}\n\n_Generated {ins.created_at.isoformat()}_\n\n{ins.body}\n"
    return {"markdown": md}


# ------------- Metrics / Intelligence Score -------------
@ttl_cache(5.0)
def _metrics_payload() -> dict:
    # Cached briefly: the dashboard polls this every few seconds and
    # compute_score() scans several tables. persist=False so this read path
    # doesn't append a Metric snapshot row on every poll — history is built by
    # the autopilot/cycle schedulers instead.
    return {"current": compute_score(persist=False), "history": score_history(days=14)}


@router.get("/metrics")
def metrics():
    try:
        return _metrics_payload()
    except Exception as e:
        logger.warning("Metrics unavailable: {}", e)
        return {"current": _empty_metrics_snapshot(), "history": []}


@router.get("/usage/summary")
def usage_summary(hours: int = 24, s: Session = Depends(_db)):
    """Per-provider+purpose breakdown of LLM token usage in the recent window."""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    try:
        rows = (
            s.query(
                Usage.provider, Usage.model, Usage.purpose,
                func.count(Usage.id),
                func.sum(Usage.input_tokens),
                func.sum(Usage.output_tokens),
                func.avg(Usage.latency_ms),
            )
            .filter(Usage.created_at >= cutoff)
            .group_by(Usage.provider, Usage.model, Usage.purpose)
            .all()
        )
        by_purpose = [
            {
                "provider": r[0], "model": r[1], "purpose": r[2],
                "calls": int(r[3] or 0),
                "input_tokens": int(r[4] or 0),
                "output_tokens": int(r[5] or 0),
                "avg_latency_ms": int(r[6] or 0),
            }
            for r in rows
        ]
        totals = {
            "calls": sum(x["calls"] for x in by_purpose),
            "input_tokens": sum(x["input_tokens"] for x in by_purpose),
            "output_tokens": sum(x["output_tokens"] for x in by_purpose),
        }
        return {"hours": hours, "totals": totals, "by_purpose": by_purpose}
    except Exception as e:
        logger.warning("Usage summary unavailable: {}", e)
        return {
            "hours": hours,
            "totals": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
            "by_purpose": [],
        }


# ------------- Jobs -------------
@router.get("/jobs", response_model=list[JobOut])
def list_jobs(limit: int = 50, s: Session = Depends(_db)):
    return s.execute(select(Job).order_by(desc(Job.created_at)).limit(limit)).scalars().all()


@router.get("/jobs/stats")
def jobs_stats(s: Session = Depends(_db)):
    """Queue depth + recent job status counts."""
    from sqlalchemy import func

    from app.workers.inproc_queue import queue_stats

    rows = s.execute(
        select(Job.status, func.count().label("n"))
        .group_by(Job.status)
    ).all()
    counts = {r.status: r.n for r in rows}
    q = queue_stats()
    failed = s.execute(
        select(Job.id, Job.kind, Job.target_id, Job.detail)
        .where(Job.status == "failed")
        .order_by(desc(Job.created_at))
        .limit(5)
    ).all()
    return {
        "queued_db": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "succeeded": counts.get("succeeded", 0),
        "failed": counts.get("failed", 0),
        "queue_depth": q["queued"],
        "active_workers": q["active"],
        "recent_failures": [
            {"id": row.id, "kind": row.kind, "target_id": row.target_id, "detail": (row.detail or "")[:240]}
            for row in failed
        ],
    }


# ------------- Live feed (SSE) -------------
@router.get("/feed/stream")
@limiter.exempt  # long-lived stream — a default per-minute cap would kill reconnects
async def feed_stream(backlog: int = Query(20, ge=0, le=200)):
    """Server-sent events of the research feed (Redis-backed pubsub)."""

    async def gen():
        yield "retry: 3000\n\n"
        if backlog > 0:
            for i, ev in enumerate(reversed(redis_client.recent_events(backlog))):
                norm = _normalize_event(ev, fallback_ms=int(time.time() * 1000) - ((backlog - i) * 10))
                yield f"id: {norm['_event_id']}\ndata: {json.dumps(norm)}\n\n"
        # subscribe live
        pubsub = redis_client.client().pubsub()
        pubsub.subscribe(redis_client.FEED_KEY)
        try:
            while True:
                # pubsub.get_message blocks up to `timeout`; run it off the event
                # loop so this coroutine doesn't stall every other request for ~1s
                # per idle poll (a single SSE client would otherwise serialize the
                # whole async server).
                msg = await asyncio.to_thread(
                    pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0
                )
                if msg and msg.get("type") == "message":
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode()
                    try:
                        norm = _normalize_event(json.loads(data))
                        payload = json.dumps(norm)
                    except Exception:
                        payload = data
                        norm = {"_event_id": f"raw:{hashlib.sha1(str(data).encode('utf-8')).hexdigest()[:16]}"}
                    yield f"id: {norm['_event_id']}\ndata: {payload}\n\n"
                else:
                    await asyncio.sleep(0.3)
        finally:
            try:
                pubsub.unsubscribe(redis_client.FEED_KEY)
                pubsub.close()
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/feed/recent")
def feed_recent(limit: int = 50):
    try:
        now = int(time.time() * 1000)
        return [
            _normalize_event(ev, fallback_ms=now - (idx * 10))
            for idx, ev in enumerate(redis_client.recent_events(limit))
        ]
    except Exception as e:
        logger.warning("Feed unavailable: {}", e)
        return []


# ─── Chat ("Ask EvoMind") ──────────────────────────────────────────────────
# A user-driven conversational surface over the corpus. Reuses the solver's
# hybrid retrieval + grounded answering (app.modules.chat) rather than
# reimplementing it.

@router.post("/chat", response_model=ChatReply, dependencies=[Depends(require_api_key)])
@limiter.limit(get_settings().rate_limit_chat)
def chat(request: Request, req: ChatRequest):
    from app.modules.chat import answer_chat

    message = (req.message or "").strip()
    if not message:
        raise HTTPException(400, "message must not be empty")
    try:
        return answer_chat(message, req.conversation_id)
    except ValueError as e:
        # Unknown conversation_id, empty message, etc.
        raise HTTPException(404, str(e)) from e


@router.get("/chat/conversations", response_model=list[ConversationOut])
def list_conversations(limit: int = 50, s: Session = Depends(_db)):
    rows = (
        s.execute(
            select(Conversation).order_by(desc(Conversation.updated_at)).limit(limit)
        )
        .scalars()
        .all()
    )
    return rows


@router.get("/chat/conversations/{conversation_id}", response_model=list[ChatMessageOut])
def conversation_messages(conversation_id: str, s: Session = Depends(_db)):
    conv = s.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    rows = (
        s.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(asc(ChatMessage.created_at))
        )
        .scalars()
        .all()
    )
    return rows


@router.delete("/chat/conversations/{conversation_id}", dependencies=[Depends(require_api_key)])
def delete_conversation(conversation_id: str, s: Session = Depends(_db)):
    conv = s.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    s.delete(conv)
    s.commit()
    return {"ok": True}


# ─── Backup / restore ──────────────────────────────────────────────────────
# Postgres/SQLite is the source of truth; Qdrant + Neo4j are derivable and
# captured best-effort. See app/modules/backup.

@router.post("/backup/now", dependencies=[Depends(require_api_key)])
def backup_now():
    from app.modules.backup import create_backup
    return create_backup()


@router.get("/backup/status")
def backup_status_route():
    from app.modules.backup import backup_status
    return backup_status()


@router.get("/backup/list")
def backup_list_route():
    from app.modules.backup import list_backups
    return list_backups()


@router.get("/backup/{backup_id}/download", dependencies=[Depends(require_api_key)])
def backup_download(backup_id: str):
    import shutil

    from app.modules.backup import backup_dir_path

    # Reject anything that isn't a plain backup id (defends against traversal).
    if "/" in backup_id or "\\" in backup_id or ".." in backup_id:
        raise HTTPException(400, "invalid backup id")
    folder = backup_dir_path() / backup_id
    if not folder.is_dir():
        raise HTTPException(404, "backup not found")

    archive_base = backup_dir_path() / f"{backup_id}"
    zip_path = shutil.make_archive(str(archive_base), "zip", root_dir=str(folder))
    return FileResponse(zip_path, media_type="application/zip", filename=f"evomind-backup-{backup_id}.zip")


# ─── Evaluation & feedback ─────────────────────────────────────────────────
# Answer-quality eval (LLM judge over cited answers) + human thumbs feedback.

@router.post("/eval/run", dependencies=[Depends(require_api_key)])
def eval_run(req: EvalRequest | None = None):
    from app.modules.eval import run_eval
    return run_eval(sample_size=(req.sample_size if req else 20))


@router.get("/eval/history")
def eval_history_route(days: int = 30):
    from app.modules.eval import eval_history
    return eval_history(days=days)


@router.post("/feedback", dependencies=[Depends(require_api_key)])
def submit_feedback(req: FeedbackRequest, s: Session = Depends(_db)):
    fb = Feedback(
        target_kind=req.target_kind, target_id=req.target_id,
        rating=req.rating, note=req.note,
    )
    s.add(fb)
    s.commit()
    return {"ok": True, "id": fb.id}


@router.get("/feedback/summary")
def feedback_summary(s: Session = Depends(_db)):
    up = s.query(func.count(Feedback.id)).filter(Feedback.rating > 0).scalar() or 0
    down = s.query(func.count(Feedback.id)).filter(Feedback.rating < 0).scalar() or 0
    total = up + down
    return {
        "up": int(up),
        "down": int(down),
        "total": int(total),
        "approval_rate": round(up / total, 3) if total else 0.0,
    }
