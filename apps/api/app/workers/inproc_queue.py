"""In-process bounded ingest queue with a fixed worker-thread pool.

Replaces the "one thread per file" pattern that caused SQLite write storms and
NVIDIA rate-limit exhaustion when ingesting 100+ PDFs at once.

Workers: configurable via INGEST_WORKERS env var (default 2).
Queue:   bounded at 2000 items — submits beyond that raise queue.Full.
"""
from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Queue item
# ---------------------------------------------------------------------------

@dataclass
class _IngestJob:
    file_path: str
    doc_id: str
    job_id: str


# ---------------------------------------------------------------------------
# Singleton state — module-level so the pool starts once per process
# ---------------------------------------------------------------------------

_q: queue.Queue[_IngestJob | None] = queue.Queue(maxsize=2000)
_active_count = 0
_active_lock = threading.Lock()
_started = False
_start_lock = threading.Lock()


def _worker() -> None:
    global _active_count
    while True:
        item = _q.get()
        if item is None:          # poison pill — shut down this worker
            _q.task_done()
            break
        with _active_lock:
            _active_count += 1
        try:
            _run_ingest(item)
        finally:
            with _active_lock:
                _active_count -= 1
            _q.task_done()


def _run_ingest(item: _IngestJob) -> None:
    from app.db import postgres
    from app.db.models import Job
    from app.ingestion.pipeline import ingest_pdf

    job_id = item.job_id

    # Mark running
    try:
        with postgres.session_scope() as s:
            j = s.get(Job, job_id)
            if j:
                j.status = "running"
                j.started_at = datetime.utcnow()
    except Exception:
        logger.debug("Could not mark job {} running", job_id)

    try:
        ingest_pdf(item.file_path, document_id=item.doc_id)
        with postgres.session_scope() as s:
            j = s.get(Job, job_id)
            if j:
                j.status = "succeeded"
                j.progress = 1.0
                j.finished_at = datetime.utcnow()
        logger.info("Ingest succeeded: {}", item.file_path)
    except Exception as e:
        tb = traceback.format_exc()
        logger.warning("Ingest failed for {}: {}", item.file_path, e)
        try:
            with postgres.session_scope() as s:
                j = s.get(Job, job_id)
                if j:
                    j.status = "failed"
                    j.finished_at = datetime.utcnow()
                    j.detail = f"{type(e).__name__}: {str(e)[:300]} | {tb[-400:]}"
        except Exception:
            pass


def _ensure_started() -> None:
    global _started
    with _start_lock:
        if _started:
            return
        n = max(1, min(int(get_settings().ingest_workers), 8))
        for _ in range(n):
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
        logger.info("Ingest worker pool started ({} workers)", n)
        _started = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def submit_ingest(file_path: str, doc_id: str, job_id: str) -> None:
    """Enqueue a PDF for ingest. Returns immediately; raises queue.Full if backlogged."""
    _ensure_started()
    _q.put_nowait(_IngestJob(file_path=file_path, doc_id=doc_id, job_id=job_id))


def queue_stats() -> dict:
    """Snapshot of queue depth and active worker count."""
    return {
        "queued": _q.qsize(),
        "active": _active_count,
    }


def recover_orphaned_jobs() -> dict:
    """Find Jobs left in `queued` or `running` from a previous process and
    either re-enqueue (if the source PDF still exists) or mark them failed.

    Without this, restarting the API process would permanently strand any
    work-in-flight: the in-memory queue resets to empty but the DB still
    thinks 250 jobs are pending. Worse, content-hash dedup would skip
    those PDFs forever because their pre-registered Documents have hashes.
    """
    import os
    from datetime import datetime

    from app.db import postgres
    from app.db.models import Document, Job

    requeued = 0
    abandoned = 0

    try:
        with postgres.session_scope() as s:
            stale = s.query(Job).filter(
                Job.kind == "ingest",
                Job.status.in_(("queued", "running")),
            ).all()

            for j in stale:
                # Find the matching Document and check if its source file exists.
                doc = s.get(Document, j.target_id) if j.target_id else None
                path = doc.path if doc else None
                if path and os.path.exists(path):
                    # Re-enqueue. The pipeline's update-or-create logic will
                    # handle the pre-registered Document shell correctly.
                    try:
                        _ensure_started()
                        _q.put_nowait(_IngestJob(file_path=path, doc_id=doc.id, job_id=j.id))
                        # Reset job state so it shows as queued again
                        j.status = "queued"
                        j.started_at = None
                        j.finished_at = None
                        requeued += 1
                    except queue.Full:
                        # If the queue is somehow already full, mark as failed.
                        j.status = "failed"
                        j.finished_at = datetime.utcnow()
                        j.detail = (j.detail or "")[:200] + " | abandoned (queue full)"
                        if doc:
                            doc.status = "failed"
                        abandoned += 1
                else:
                    # File is gone — mark both job and pre-registered Document as failed
                    # so the user can see what happened, and so dedup doesn't keep
                    # blocking re-uploads of identical content.
                    j.status = "failed"
                    j.finished_at = datetime.utcnow()
                    j.detail = (j.detail or "")[:200] + " | abandoned (source file missing after restart)"
                    if doc and doc.status == "pending":
                        doc.status = "failed"
                    abandoned += 1

        if requeued or abandoned:
            logger.info(
                "queue: recovered orphaned jobs — requeued={}, abandoned={}",
                requeued, abandoned,
            )
    except Exception as e:
        logger.warning("queue: orphan recovery failed: {}", e)

    return {"requeued": requeued, "abandoned": abandoned}
